"""
Audit middleware — auto-logs INSERT/UPDATE/DELETE on critical tables.

Hooks into SQLAlchemy session events. Writes to audit_log table.
Usage: call `init_audit()` once at startup.
Call `set_audit_user(user_id, user_name, db)` desde la dependencia de auth
para que la escritura quede atribuida. **La sesion no es opcional en el flujo
de la API**: ver la docstring de `set_audit_user`.
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
    "reporte_energia_generacion",
    "reporte_energia_consumo",
})

# Solo sirve dentro de un mismo contexto de ejecucion: los seeds de arranque y
# el scheduler, que escriben en el hilo donde se llamo a set_audit_user. Para la
# API no alcanza -- ver `set_audit_user`.
_audit_user: ContextVar[tuple[int | None, str | None]] = ContextVar(
    "_audit_user", default=(None, None)
)


def set_audit_user(
    user_id: int | None,
    user_name: str | None,
    session: Session | None = None,
) -> None:
    """Registra quien escribe, para que `audit_log` lo pueda atribuir.

    `session` es lo que hace que funcione desde la API, y no es un detalle:
    FastAPI ejecuta las dependencias `def` y los endpoints `def` en llamadas
    distintas a `run_in_threadpool`, y cada una recibe una **copia** del
    contexto. Un ContextVar escrito en la dependencia muere con esa copia y el
    endpoint lee el default -- que es como `audit_log` acumulo tres meses de
    filas sin autor en las 10 tablas auditadas.

    La sesion, en cambio, es el mismo objeto en las dos: FastAPI cachea
    `Depends(get_db)` por peticion, asi que la dependencia y el endpoint
    reciben la misma instancia, y el autor viaja con ella hasta el flush.

    Sin `session` cae al ContextVar, que sigue siendo lo correcto para los
    seeds de arranque y el scheduler: corren en su propio hilo y el flush pasa
    por el mismo contexto donde se seteo.
    """
    if session is not None:
        session.info["audit_user"] = (user_id, user_name)
    else:
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
            old = _serialize(hist.deleted[0] if hist.deleted else None)
            new = _serialize(hist.added[0] if hist.added else None)
            # Se compara DESPUES de serializar, y no antes. Las columnas de
            # dinero son NUMERIC, asi que el valor cargado es un Decimal y el
            # que llega del JSON del PATCH es un float:
            # `Decimal('0.0380') != 0.038` es True en Python aunque sea el mismo
            # numero. Comparando crudo, 22 de las 25 filas del historico de
            # tarifas quedaron registradas como cambios que decian
            # {"antes": 0.038, "despues": 0.038}. Ver D-24 §e.
            if old != new:
                changes[attr.key] = {"antes": old, "despues": new}
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

    # La sesion primero: es la unica via que sobrevive al threadpool de FastAPI.
    user_id, user_name = session.info.get("audit_user") or _audit_user.get()

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
