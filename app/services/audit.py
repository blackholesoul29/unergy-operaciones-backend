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
import re
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


def _autor(session: Session) -> tuple[int | None, str | None]:
    """Quien esta escribiendo. La sesion primero: es la unica via que sobrevive
    al threadpool de FastAPI (ver `set_audit_user`). El ContextVar queda para
    los seeds de arranque y el scheduler."""
    return session.info.get("audit_user") or _audit_user.get()


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

    user_id, user_name = _autor(session)

    session._audit_queue.append({
        "tabla": table,
        "registro_id": pk,
        "accion": action,
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "cambios": json.dumps(cambios) if cambios else None,
    })


_INSERT_AUDIT_BASE = (
    "INSERT INTO audit_log "
    "(tabla, registro_id, accion, usuario_id, usuario_nombre, cambios) "
    "VALUES (:tabla, :registro_id, :accion, :usuario_id, :usuario_nombre, {cambios})"
)


def _insert_audit(dialecto: str) -> str:
    """El INSERT, con el CAST a jsonb solo donde existe jsonb.

    En SQLite `CAST(x AS jsonb)` no falla: aplica afinidad numerica y guarda un
    0 en vez del JSON, en silencio. Los tests del merge corren sobre SQLite, asi
    que el CAST tiene que depender del dialecto y no del optimismo.
    """
    return _INSERT_AUDIT_BASE.format(
        cambios="CAST(:cambios AS jsonb)" if dialecto == "postgresql" else ":cambios")

# Nombre de tabla valido. `registrar_borrado` lo interpola en el SQL, asi que
# no puede aceptar cualquier cosa aunque hoy solo lo llamen con literales.
_NOMBRE_TABLA = re.compile(r"^[a-z_][a-z0-9_]*$")


def registrar_borrado(
    session: Session,
    tabla: str,
    registro_id: int,
    *,
    contexto: dict | None = None,
    tipo: str = "hard",
) -> bool:
    """Deja constancia de un borrado que los hooks del ORM no van a ver.

    Los borrados masivos --`DELETE FROM x WHERE ...`-- no pasan por el unit of
    work, asi que `_queue_audit` nunca se entera. Los dos endpoints de fusion de
    duplicados borran asi, y hasta el 2026-08-27 **borrar una planta no dejaba
    ni una fila en `audit_log`**: la operacion mas destructiva de la app era la
    unica sin rastro.

    Guarda el **snapshot completo de la fila** antes de que desaparezca, que es
    justo lo que un hook generico sobre `do_orm_execute` no podria dar: ese ve
    la sentencia y el rowcount, no el contenido.

    ⚠️ **Hay que llamarla ANTES de tocar la fila.** Los dos merges vacian campos
    del perdedor antes de borrarlo (`UPDATE ... SET campo=NULL WHERE id=:loser`),
    asi que llamarla al final guardaria una foto ya mutilada.

    El `SELECT *` es deliberado: enumerar columnas a mano queda viejo en dias
    --upstream lleva diez revisiones esta semana borrando columnas de
    `proyectos`-- y ademas funciona en cualquier dialecto, que `row_to_json` no.

    Devuelve False si la fila no existe: no hay nada que retratar.
    """
    if not _NOMBRE_TABLA.match(tabla):
        raise ValueError(f"nombre de tabla no valido: {tabla!r}")

    fila = session.execute(
        text(f"SELECT * FROM {tabla} WHERE id = :id"), {"id": registro_id}
    ).mappings().first()
    if fila is None:
        return False

    cambios: dict[str, Any] = {
        "snapshot": {k: _serialize(v) for k, v in fila.items()},
        "tipo_borrado": tipo,
    }
    if contexto:
        cambios["contexto"] = contexto

    user_id, user_name = _autor(session)
    session.execute(text(_insert_audit(session.get_bind().dialect.name)), {
        "tabla": tabla,
        "registro_id": registro_id,
        "accion": "DELETE",
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "cambios": json.dumps(cambios, ensure_ascii=False),
    })
    return True


def _flush_audit(session: Session) -> None:
    queue = getattr(session, "_audit_queue", None)
    if not queue:
        return

    conn = session.connection()
    for entry in queue:
        conn.execute(text(_insert_audit(conn.dialect.name)), entry)
    session._audit_queue.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Escrituras masivas
# ─────────────────────────────────────────────────────────────────────────────

# Cuanta sentencia SQL se guarda. Con esto alcanza para reconocer que corrio;
# guardar un UPDATE gigante entero solo engorda la tabla.
_MAX_SENTENCIA = 2000


def _tabla_del_statement(state) -> str | None:
    """La tabla que toca un UPDATE/DELETE del ORM, o None si no se puede saber."""
    ent = getattr(state.statement, "entity_description", None)
    if not ent:
        return None
    tabla = ent.get("table")
    return getattr(tabla, "name", None)


def _registrar_masivo(session: Session, tabla: str, accion: str,
                      sentencia: str, filas: int | None) -> None:
    cambios = {
        "masiva": True,
        "filas_afectadas": filas,
        "sentencia": sentencia[:_MAX_SENTENCIA],
    }
    user_id, user_name = _autor(session)
    session.execute(text(_insert_audit(session.get_bind().dialect.name)), {
        "tabla": tabla,
        # No hay UNA fila: la sentencia afecto a muchas. 0 es el centinela, y
        # `cambios.masiva` es lo que hay que mirar para no confundirlo con la
        # fila de id 0, que no existe en ninguna tabla de este esquema.
        "registro_id": 0,
        "accion": accion,
        "usuario_id": user_id,
        "usuario_nombre": user_name,
        "cambios": json.dumps(cambios, ensure_ascii=False),
    })


def init_audit_masivo():
    """Audita los UPDATE/DELETE masivos, que `before_flush` no puede ver.

    Un `UPDATE ... WHERE` no crea objetos en `session.dirty`: el unit of work no
    participa, asi que `_queue_audit` nunca se entera. Asi estuvo `tipo_migration`
    reescribiendo 5.086 fallas en cada arranque durante 23 arranques sin dejar
    una sola fila en `audit_log`.

    Deja **una fila resumen por sentencia** -- no una por registro -- con la
    tabla, la sentencia y cuantas filas toco. `registro_id` va en 0: no hay una
    fila que senalar.

    🛑 **LO QUE ESTO NO CUBRE, y es mucho:**

    - **Las 32 escrituras de SQL crudo por `text()`.** Verificado: para esas,
      `is_update` e `is_delete` son False y `is_orm_statement` tambien --
      SQLAlchemy no las parsea, asi que no hay forma de saber si son un UPDATE
      ni sobre que tabla caen. **De esas, 16 ni siquiera tienen el nombre de la
      tabla escrito literal** (`UPDATE {t} SET ...`, el patron de los endpoints
      de fusion): ni este hook ni el escaner estatico pueden atribuirlas. La
      unica cobertura posible ahi es explicita, sitio por sitio, como hace
      `registrar_borrado()` con el merge.
    - **Lo que se escribe fuera de una `Session`**, por ejemplo con
      `engine.execute()` o desde otro proceso.
    - **El contenido.** Queda que N filas cambiaron y con que sentencia, no
      cuales ni que valor tenian antes. Para eso hace falta capturar la fila,
      que es lo que hace `registrar_borrado()`.

    O sea: esto cierra el agujero de los 38 sitios que el ORM compila (34
    `Query.update/delete` + 4 del estilo 2.0), no el de los 70 que hay.

    Devuelve el listener para poder desengancharlo con `event.remove()`: los
    tests lo necesitan, porque se registra sobre la clase `Session` y si no,
    queda activo para todo el proceso.
    """

    @event.listens_for(Session, "do_orm_execute")
    def _auditar_masivo(state):
        if not (state.is_update or state.is_delete):
            return None
        if not state.is_orm_statement:
            return None      # text() crudo: sin metadatos, no hay nada que decir
        tabla = _tabla_del_statement(state)
        if tabla not in _AUDITED_TABLES:
            return None

        # A partir de aca se toma el control de la ejecucion para poder leer el
        # rowcount, que antes de ejecutar no existe.
        resultado = state.invoke_statement()
        try:
            _registrar_masivo(
                state.session, tabla,
                "DELETE" if state.is_delete else "UPDATE",
                str(state.statement), resultado.rowcount,
            )
        except Exception as exc:
            # La escritura YA ocurrio. Tumbarla ahora por un fallo de auditoria
            # seria peor que perder el registro, asi que se avisa fuerte y se
            # sigue. Es lo contrario a `registrar_borrado()`, que corre ANTES de
            # destruir y por eso ahi si conviene que reviente.
            print(f"[audit] no se pudo registrar la escritura masiva sobre "
                  f"{tabla}: {type(exc).__name__}: {exc}")
        return resultado

    return _auditar_masivo


def init_audit() -> None:
    init_audit_masivo()

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
