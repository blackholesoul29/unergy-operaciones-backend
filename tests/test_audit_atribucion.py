"""Atribucion de autor en `audit_log`.

Regresion del hallazgo de `docs/refactor/01-decisiones.md` D-24 §e: durante tres
meses `audit_log` guardo NULL en `usuario_id`/`usuario_nombre` en las 10 tablas
auditadas. La causa no era que nadie llamara a `set_audit_user()`, sino que se
llamaba desde `get_current_user` -- una dependencia sincrona -- y FastAPI corre
la dependencia y el endpoint en llamadas distintas a `run_in_threadpool`, cada
una con su propia copia del contexto.

Estos tests no necesitan base de datos: `_queue_audit` solo encola el dict que
despues se inserta, y `Session()` sin bind ya trae el `.info` que transporta al
autor.
"""
import contextvars

import anyio
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.models.proyectos import Proyecto  # tabla auditada
from app.services import audit


def test_el_autor_sobrevive_al_threadpool_de_fastapi():
    """El caso real: dependencia y endpoint en dos llamadas al threadpool."""
    session = Session()
    proyecto = Proyecto(id=1)

    def dependencia():   # como get_current_user
        audit.set_audit_user(7, "Juan Jose", session)

    def endpoint():      # como update_contrato
        audit._queue_audit(session, "INSERT", proyecto)

    async def peticion():
        await run_in_threadpool(dependencia)
        await run_in_threadpool(endpoint)

    anyio.run(peticion)

    entrada = session._audit_queue[0]
    assert entrada["usuario_id"] == 7
    assert entrada["usuario_nombre"] == "Juan Jose"


def test_por_que_la_sesion_y_no_el_contextvar():
    """Deja fijo el mecanismo del bug, para que nadie lo revierta por 'limpieza'.

    Un ContextVar escrito dentro de `run_in_threadpool` no vuelve al contexto
    de quien llamo, asi que la siguiente llamada lee el default.
    """
    v = contextvars.ContextVar("prueba", default=(None, None))

    async def peticion():
        await run_in_threadpool(lambda: v.set((7, "Juan Jose")))
        return await run_in_threadpool(v.get)

    assert anyio.run(peticion) == (None, None)


def test_los_seeds_de_arranque_siguen_atribuidos_sin_sesion():
    """El camino del ContextVar sigue vivo: los seeds corren en un solo hilo."""

    def hilo_del_seed():
        audit.set_audit_user(None, "sistema (seed de arranque)")
        session = Session()
        audit._queue_audit(session, "INSERT", Proyecto(id=2))
        return session._audit_queue[0]

    # copy_context aisla el set: sin esto el ContextVar se filtra a otros tests.
    entrada = contextvars.copy_context().run(hilo_del_seed)

    assert entrada["usuario_id"] is None
    assert entrada["usuario_nombre"] == "sistema (seed de arranque)"


def test_la_sesion_le_gana_a_un_contextvar_viejo():
    """Si las dos vias traen valor, manda la de la peticion."""

    def con_contextvar_sucio():
        audit.set_audit_user(None, "sistema (seed de arranque)")
        session = Session()
        audit.set_audit_user(7, "Juan Jose", session)
        audit._queue_audit(session, "INSERT", Proyecto(id=3))
        return session._audit_queue[0]

    entrada = contextvars.copy_context().run(con_contextvar_sucio)

    assert entrada["usuario_nombre"] == "Juan Jose"


def test_init_audit_ya_no_rotula_todo_el_arranque(monkeypatch):
    """El rotulo lo pone `_deferred_init` tarea por tarea, no `_run_init_audit`.

    Con un solo rotulo para las 22 tareas, las 50.860 filas de `audit_log` del
    2026-08-27 quedaron sin poder atribuirse a ninguna. Ver D-24 §e.
    """
    import inspect

    from app import main

    llamadas = []
    monkeypatch.setattr(audit, "init_audit", lambda: llamadas.append("init_audit"))
    monkeypatch.setattr(audit, "set_audit_user",
                        lambda *a, **k: llamadas.append(("set_audit_user",) + a))

    main._run_init_audit()

    assert llamadas == ["init_audit"], "engancha los hooks, pero ya no firma nada"
    assert "sistema (startup: {label})" in inspect.getsource(main._deferred_init)
