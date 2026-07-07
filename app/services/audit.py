"""
Audit middleware — auto-logs INSERT/UPDATE/DELETE on critical tables.

Hooks into SQLAlchemy session events. Writes to audit_log table.
Usage: call `init_audit(engine)` once at startup.
Call `set_audit_user(db, user_id, user_name)` in endpoints that
need user attribution (via get_current_user dependency).
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, text, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_AUDITED_TABLES: frozenset[str] = frozenset({
    "proyectos",
    "ppa_contratos",
    "liquidaciones",
    "fallas",
    "clientes",
    "fronteras",
    "contratos_servicio",
    "generacion_diaria",
})

_audit_user: ContextVar[tuple[int | None, str | None]] = ContextVar(
    "_audit_user", default=(None, None)
)


def set_audit_user(user_id: int | None, user_name: str | None) -> None:
    _audit_user.set((user_id, user_name))


def _table_name(obj: Any) -> str | None:
    mapper = inspect(type(obj), raiseerr=False)
    if mapper is None:
        return None
    return mapper.persist_selectable.name


def _get_pk(obj: Any) -> int | None:
    mapper = inspect(type(obj))
    pk_cols = mapper.primary_key
    if pk_cols:
        return getattr(obj, pk_cols[0].name, None)
    return None


def _serialize(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    from datetime import date as _date
    if isinstance(v, _date):
        return v.isoformat()
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "value"):
        return v.value
    return str(v)


def _diff_attrs(obj: Any) -> dict[str, dict[str, Any]] | None:
    insp = inspect(obj)
    mapper = inspect(type(obj))
    column_keys = {c.key for c in mapper.column_attrs}
    changes = {}
    for attr in insp.attrs:
        if attr.key not in column_keys:
            continue
        hist = attr.history
        if hist.has_changes():
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old != new:
                changes[attr.key] = {
                    "antes": _serialize(old),
                    "despues": _serialize(new),
                }
    return changes or None


def _queue_audit(session: Session, action: str, obj: Any) -> None:
    table = _table_name(obj)
    if table not in _AUDITED_TABLES:
        return

    pk = _get_pk(obj)
    if pk is None:
        return

    cambios: dict | None = None
    if action == "UPDATE":
        cambios = _diff_attrs(obj)
        if not cambios:
            return

    if not hasattr(session, "_audit_queue"):
        session._audit_queue = []

    user_id, user_name = _audit_user.get()

    session._audit_queue.append({
        "tabla": table,
        "registro_id": pk,
        "accion": action,
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "cambios": json.dumps(cambios) if cambios else None,
    })


def _flush_audit(session: Session) -> None:
    queue = getattr(session, "_audit_queue", None)
    if not queue:
        return

    conn = session.connection()
    for entry in queue:
        conn.execute(
            text(
                "INSERT INTO audit_log "
                "(tabla, registro_id, accion, usuario_id, usuario_nombre, cambios) "
                "VALUES (:tabla, :registro_id, :accion, :usuario_id, :usuario_nombre, CAST(:cambios AS jsonb))"
            ),
            entry,
        )
    session._audit_queue.clear()


def init_audit() -> None:
    @event.listens_for(Session, "before_flush")
    def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
        for obj in session.new:
            _queue_audit(session, "INSERT", obj)
        for obj in session.dirty:
            if session.is_modified(obj, include_collections=False):
                _queue_audit(session, "UPDATE", obj)
        for obj in session.deleted:
            _queue_audit(session, "DELETE", obj)

    @event.listens_for(Session, "after_flush")
    def _after_flush(session: Session, flush_context: Any) -> None:
        _flush_audit(session)


# ────────────────────────────────────────────────────────────────────────────
# Monitoreo proactivo — procesa audit_log y dispara alertas configurables.
# ────────────────────────────────────────────────────────────────────────────
import logging  # noqa: E402
from typing import Optional  # noqa: E402

from sqlalchemy.orm import Session as _Session  # noqa: E402

logger = logging.getLogger("audit.monitor")


class AuditMonitorService:
    """Lee registros de `audit_log`, aplica `AuditRuleEngine` y, ante una
    coincidencia, crea una `AuditAlert` (anti-duplicados por fingerprint) y la
    notifica vía `NotificationService`.

    El scan periódico lo dispara APScheduler (ver `app/main.py`). El cursor de
    lectura (`_last_id`) vive en memoria: en el primer scan se inicializa al
    máximo id existente para no reprocesar el histórico; el fingerprint único
    protege contra duplicados tras un reinicio.
    """

    def __init__(self, notifier: Optional[Any] = None) -> None:
        self._notifier = notifier
        self._last_id: Optional[int] = None
        self._role_cache: dict[int, Optional[str]] = {}

    @property
    def notifier(self):
        # Import perezoso: evita costo/ciclos si nunca se notifica (p.ej. tests).
        if self._notifier is None:
            from app.services.notification_service import NotificationService
            self._notifier = NotificationService()
        return self._notifier

    # ── resolución de rol del usuario ────────────────────────────────────────
    def _resolve_rol(self, db: _Session, usuario_id: Optional[int]) -> Optional[str]:
        if usuario_id is None:
            return None
        if usuario_id in self._role_cache:
            return self._role_cache[usuario_id]
        rol = db.execute(
            text("SELECT rol FROM usuarios WHERE id = :uid"), {"uid": usuario_id}
        ).scalar()
        rol = str(rol) if rol is not None else None
        self._role_cache[usuario_id] = rol
        return rol

    # ── procesamiento de un registro ─────────────────────────────────────────
    def process_audit_log(self, db: _Session, record: dict) -> list:
        """Evalúa un registro de audit_log. Devuelve las AuditAlert creadas."""
        from app.models.audit_alert import AuditAlert
        from app.services.audit_rules import TABLE_TO_ENTITY, AuditRuleEngine

        entity_type = TABLE_TO_ENTITY.get(record.get("tabla"))
        if entity_type is None:
            return []

        cambios = record.get("cambios")
        if isinstance(cambios, str):
            try:
                cambios = json.loads(cambios)
            except (ValueError, TypeError):
                cambios = None

        rol = self._resolve_rol(db, record.get("usuario_id"))
        overrides = self._load_rule_overrides(db, entity_type)

        triggered = AuditRuleEngine.evaluate(
            entity_type=entity_type,
            accion=record.get("accion", ""),
            cambios=cambios,
            rol=rol,
            when=record.get("created_at"),
            overrides=overrides,
        )
        if not triggered:
            return []

        rule_name = (overrides or {}).get("_rule_name")
        created: list = []
        for t in triggered:
            fingerprint = f"{record.get('id')}:{t['reason']}"
            exists = db.execute(
                text("SELECT 1 FROM audit_alerts WHERE fingerprint = :fp"),
                {"fp": fingerprint},
            ).scalar()
            if exists:
                continue

            alert = AuditAlert(
                rule_name=rule_name or t["reason"],
                entity_type=entity_type,
                entity_id=str(record.get("registro_id")),
                trigger_reason=t["detalle"],
                severity=t["severity"],
                status="pending",
                fingerprint=fingerprint,
                audit_log_id=record.get("id"),
                usuario_nombre=record.get("usuario_nombre"),
                detalle=t.get("meta"),
                notificado=False,
            )
            db.add(alert)
            db.flush()  # obtiene id + timestamp para la notificación
            db.refresh(alert)

            try:
                result = self.notifier.dispatch(alert)
                alert.notificado = bool(result.get("slack") or result.get("email"))
            except Exception as exc:  # noqa: BLE001 — notificar nunca rompe el scan
                logger.warning("[audit_monitor] fallo notificando alerta %s: %s", alert.id, exc)

            created.append(alert)

        db.commit()
        return created

    def _load_rule_overrides(self, db: _Session, entity_type: str) -> Optional[dict]:
        """Regla activa (AuditRule) para el tipo de entidad, si existe."""
        row = db.execute(
            text(
                "SELECT name, condition_json FROM audit_rules "
                "WHERE entity_type = :et AND active = TRUE "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"et": entity_type},
        ).first()
        if row is None:
            return None
        overrides = dict(row[1]) if isinstance(row[1], dict) else {}
        overrides["_rule_name"] = row[0]
        return overrides

    # ── scan periódico ───────────────────────────────────────────────────────
    def scan(self, db: _Session, *, limit: int = 500) -> list:
        """Procesa los registros de audit_log nuevos desde el último scan."""
        if self._last_id is None:
            # Primer arranque: no reprocesar el histórico.
            self._last_id = db.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM audit_log")
            ).scalar() or 0
            return []

        rows = db.execute(
            text(
                "SELECT id, tabla, registro_id, accion, usuario_id, usuario_nombre, "
                "cambios, created_at FROM audit_log "
                "WHERE id > :last ORDER BY id ASC LIMIT :lim"
            ),
            {"last": self._last_id, "lim": limit},
        ).mappings().all()

        created: list = []
        for row in rows:
            record = dict(row)
            try:
                created.extend(self.process_audit_log(db, record))
            except Exception as exc:  # noqa: BLE001 — un registro malo no frena el resto
                db.rollback()
                logger.warning("[audit_monitor] fallo procesando audit_log %s: %s", record.get("id"), exc)
            self._last_id = record["id"]
        return created


# Singleton usado por el scheduler (mantiene el cursor entre corridas).
audit_monitor = AuditMonitorService()
