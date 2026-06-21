"""Propagación diaria de la maestra de clientes hacia los contratos PPA.

Detecta cambios en los datos de las partes de un cliente (Nombre y NIT) y los
propaga a las columnas denormalizadas de los contratos PPA activos donde ese
cliente figura como comprador o vendedor. Cada campo propagado deja una fila
inmutable en `cliente_ppa_audit_log`. Un cambio de NIT es crítico: marca el
contrato para revisión legal (`requires_manual_review`) y genera una alerta.

El diffing es puro (sin BD) para poder probarse aisladamente; la orquestación
(`ClientPpaSyncService`) hace las consultas, escribe la bitácora y notifica.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

logger = logging.getLogger("sync_client_ppa")

# Sufijo de los campos que se consideran críticos (cambio de NIT).
_CRITICAL_SUFFIX = "_nit"

# Roles de usuario a los que se avisa ante un cambio crítico de NIT.
_ROLES_NOTIFICAR = ("admin", "operaciones", "liquidaciones")

TRIGGERED_BY_SYSTEM = "system_job"
TRIGGERED_BY_MANUAL = "manual"


@dataclass(frozen=True)
class FieldChange:
    """Un cambio de un único campo detectado entre el cliente y el PPA."""

    field_changed: str
    old_value: str | None
    new_value: str | None
    is_critical: bool


def _norm(v: object) -> str | None:
    """Normaliza a string limpio; '' y whitespace se tratan como None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _role_diff(role: str, cliente, ppa) -> list[FieldChange]:
    """Compara nombre y NIT del cliente contra las columnas `<role>_*` del PPA."""
    pairs = (
        (f"{role}_nombre", getattr(ppa, f"{role}_nombre", None), cliente.razon_social_nombre),
        (f"{role}_nit", getattr(ppa, f"{role}_nit", None), cliente.nit_cedula),
    )
    changes: list[FieldChange] = []
    for field, old, new in pairs:
        old_n, new_n = _norm(old), _norm(new)
        if old_n != new_n:
            changes.append(FieldChange(field, old_n, new_n, field.endswith(_CRITICAL_SUFFIX)))
    return changes


def diff_cliente_ppa(cliente, ppa) -> list[FieldChange]:
    """Lista los campos del PPA que difieren del cliente, según su(s) rol(es).

    Función pura: `cliente` y `ppa` solo necesitan exponer atributos
    (sirven instancias ORM o SimpleNamespace).
    """
    changes: list[FieldChange] = []
    if getattr(ppa, "comprador_id", None) == cliente.id:
        changes.extend(_role_diff("comprador", cliente, ppa))
    if getattr(ppa, "vendedor_id", None) == cliente.id:
        changes.extend(_role_diff("vendedor", cliente, ppa))
    return changes


def apply_changes(ppa, changes: list[FieldChange]) -> bool:
    """Aplica los cambios sobre el PPA in-place. Devuelve True si hubo cambios."""
    if not changes:
        return False
    for ch in changes:
        setattr(ppa, ch.field_changed, ch.new_value)
    return True


class ClientPpaSyncService:
    """Orquesta la propagación Cliente → PPA contra la base de datos."""

    def __init__(self, db):
        self.db = db

    # ── API pública ──────────────────────────────────────────────────────────
    def run_daily_sync(
        self,
        since: datetime | None = None,
        notify: bool = True,
        triggered_by: str = TRIGGERED_BY_SYSTEM,
        update_state: bool = True,
        process_all: bool = False,
    ) -> dict:
        """Propaga cambios de clientes a sus PPA activos.

        `since`: solo se revisan clientes con `updated_at >= since`. Si es None se
        toma del estado persistido del job; si tampoco existe, se revisan todos.
        `process_all`: ignora el estado y revisa todos los clientes (sync manual
        forzado). Devuelve un resumen con contadores.
        """
        started = datetime.now(timezone.utc)
        if process_all:
            effective_since = None
        else:
            effective_since = since if since is not None else self._load_last_synced_at()
        clientes = self._changed_clientes(effective_since)

        summary = {
            "clientes_revisados": len(clientes),
            "contratos_actualizados": 0,
            "campos_cambiados": 0,
            "cambios_criticos": 0,
            "notificaciones": 0,
            "desde": effective_since.isoformat() if effective_since else None,
        }

        for cliente in clientes:
            for ppa in self._active_ppas_for_cliente(cliente.id):
                changes = diff_cliente_ppa(cliente, ppa)
                if not changes:
                    continue
                self._persist_contract_changes(cliente, ppa, changes, started, triggered_by)
                summary["contratos_actualizados"] += 1
                summary["campos_cambiados"] += len(changes)
                criticos = [c for c in changes if c.is_critical]
                summary["cambios_criticos"] += len(criticos)
                if criticos and notify:
                    summary["notificaciones"] += self._notify_critical(cliente, ppa, criticos)

        if update_state:
            self._save_last_synced_at(started)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("[sync_client_ppa] commit falló")
            raise

        summary["synced_at"] = started.isoformat()
        logger.info(
            "[sync_client_ppa] %s contratos actualizados, %s campos (%s críticos)",
            summary["contratos_actualizados"], summary["campos_cambiados"],
            summary["cambios_criticos"],
        )
        return summary

    # ── Helpers de BD ────────────────────────────────────────────────────────
    def _changed_clientes(self, since: datetime | None) -> list:
        from app.models import Cliente

        q = self.db.query(Cliente).filter(Cliente.deleted_at.is_(None))
        if since is not None:
            q = q.filter(Cliente.updated_at >= since)
        return q.all()

    def _active_ppas_for_cliente(self, cliente_id: int) -> list:
        from sqlalchemy import or_

        from app.models import PPAContrato

        today = date.today()
        return (
            self.db.query(PPAContrato)
            .filter(
                PPAContrato.deleted_at.is_(None),
                or_(
                    PPAContrato.comprador_id == cliente_id,
                    PPAContrato.vendedor_id == cliente_id,
                ),
                or_(PPAContrato.fecha_fin.is_(None), PPAContrato.fecha_fin >= today),
            )
            .all()
        )

    def _persist_contract_changes(self, cliente, ppa, changes, ts, triggered_by) -> None:
        from app.models import ClientePpaAuditLog

        apply_changes(ppa, changes)
        ppa.data_version = (ppa.data_version or 1) + 1
        ppa.last_data_sync = ts
        if any(c.is_critical for c in changes):
            ppa.requires_manual_review = True

        for ch in changes:
            self.db.add(ClientePpaAuditLog(
                cliente_id=cliente.id,
                ppa_id=ppa.id,
                field_changed=ch.field_changed,
                old_value=ch.old_value,
                new_value=ch.new_value,
                is_critical=ch.is_critical,
                triggered_by=triggered_by,
            ))

    def _notify_critical(self, cliente, ppa, criticos: list[FieldChange]) -> int:
        from app.models import Usuario
        from app.models.notificaciones import Notificacion, TipoNotificacionEnum

        usuarios = (
            self.db.query(Usuario)
            .filter(Usuario.activo == True, Usuario.rol.in_(list(_ROLES_NOTIFICAR)))  # noqa: E712
            .all()
        )
        if not usuarios:
            return 0

        contrato_ref = ppa.nombre_interno or ppa.numero_codigo_contrato or f"#{ppa.id}"
        detalle = "; ".join(
            f"{c.field_changed}: {c.old_value or '∅'} → {c.new_value or '∅'}" for c in criticos
        )
        titulo = f"⚠️ Cambio de NIT propagado al PPA {contrato_ref}"
        mensaje = (
            f"El NIT del cliente «{cliente.razon_social_nombre}» (#{cliente.id}) cambió y se "
            f"propagó al contrato PPA {contrato_ref} (#{ppa.id}). {detalle}. El contrato quedó "
            f"marcado para revisión legal antes de habilitar facturación automática."
        )
        link = f"/ppa/{ppa.id}"
        for u in usuarios:
            self.db.add(Notificacion(
                usuario_id=u.id,
                tipo=TipoNotificacionEnum.alerta,
                titulo=titulo,
                mensaje=mensaje,
                link=link,
            ))
        return len(usuarios)

    def _load_last_synced_at(self) -> datetime | None:
        from sqlalchemy import text

        try:
            row = self.db.execute(
                text("SELECT last_synced_at FROM cliente_ppa_sync_state WHERE id = 1")
            ).first()
            return row[0] if row and row[0] else None
        except Exception:
            logger.warning("[sync_client_ppa] no se pudo leer el estado del sync", exc_info=True)
            return None

    def _save_last_synced_at(self, ts: datetime) -> None:
        from sqlalchemy import text

        self.db.execute(
            text(
                "INSERT INTO cliente_ppa_sync_state (id, last_synced_at) VALUES (1, :ts) "
                "ON CONFLICT (id) DO UPDATE SET last_synced_at = EXCLUDED.last_synced_at"
            ),
            {"ts": ts},
        )


def run_daily_sync_job() -> dict:
    """Punto de entrada para el scheduler: abre su propia sesión y la cierra."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return ClientPpaSyncService(db).run_daily_sync()
    finally:
        db.close()
