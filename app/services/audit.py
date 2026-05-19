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
                "VALUES (:tabla, :registro_id, :accion, :usuario_id, :usuario_nombre, :cambios::jsonb)"
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
