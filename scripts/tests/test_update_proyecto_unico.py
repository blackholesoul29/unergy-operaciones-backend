"""Tests standalone (sin pytest ni BD): `python scripts/tests/test_update_proyecto_unico.py`.

Cubre el bug del "API ID Unergy" (sub_project es UNIQUE): antes, asignar un valor ya
usado por otro proyecto reventaba como IntegrityError no capturado -> 500 sin detalle
-> el frontend solo mostraba "Error". Ahora update_proyecto devuelve un 409 accionable.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.api.v1.proyectos import update_proyecto
from app.schemas.proyectos import ProyectoUpdate


class _Obj:
    """Objeto plano que acepta setattr (simula una fila Proyecto)."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeQuery:
    def __init__(self, db):
        self._db = db
    def filter(self, *a, **k):
        return self
    def options(self, *a, **k):
        return self
    def first(self):
        return self._db._results.pop(0) if self._db._results else None


class _FakeDB:
    """Devuelve resultados pre-escritos por cada .first(); registra commit/rollback."""
    def __init__(self, results, commit_raises=None):
        self._results = list(results)
        self._commit_raises = commit_raises
        self.committed = False
        self.rolled_back = False
    def query(self, *a, **k):
        return _FakeQuery(self)
    def commit(self):
        if self._commit_raises:
            raise self._commit_raises
        self.committed = True
    def rollback(self):
        self.rolled_back = True


def test_sub_project_duplicado_devuelve_409_accionable():
    """El caso real: ingresar un API ID Unergy ya usado por otro proyecto."""
    p = _Obj(id=10, nombre_comercial="La Reserva 2", sub_project=None)
    conflicto = _Obj(id=42, nombre_comercial="La Reserva 1", sub_project="lareserva")
    db = _FakeDB(results=[p, conflicto])  # 1) find p  2) busca conflicto
    data = ProyectoUpdate(sub_project="lareserva")
    try:
        update_proyecto(10, data, db=db, _=None)
        assert False, "debió lanzar HTTPException 409"
    except HTTPException as e:
        assert e.status_code == 409, e.status_code
        assert "La Reserva 1" in e.detail and "42" in e.detail
        assert "API ID Unergy" in e.detail
    assert not db.committed, "no debe commitear ante conflicto"


def test_integrityerror_en_commit_se_traduce_a_409():
    """Backstop: carrera/constraint no detectada proactivamente -> 409, no 500."""
    p = _Obj(id=10, nombre_comercial="La Reserva 2", sub_project=None)
    err = IntegrityError("INSERT...", {}, Exception("duplicate key"))
    db = _FakeDB(results=[p, None], commit_raises=err)  # find p, sin conflicto previo
    data = ProyectoUpdate(sub_project="nuevo")
    try:
        update_proyecto(10, data, db=db, _=None)
        assert False, "debió lanzar HTTPException 409"
    except HTTPException as e:
        assert e.status_code == 409, e.status_code
        assert e.detail  # mensaje no vacío (a diferencia del 500 opaco)
    assert db.rolled_back, "debe hacer rollback tras IntegrityError"


def test_update_sin_campos_unicos_no_choca():
    """Editar un campo normal no dispara el chequeo de unicidad ni 409."""
    p = _Obj(id=10, nombre_comercial="X", sub_project=None)
    # results: 1) find p (update)  2) _get_proyecto_or_404 al final
    db = _FakeDB(results=[p, p])
    data = ProyectoUpdate(nombre_comercial="Nuevo Nombre")
    out = update_proyecto(10, data, db=db, _=None)
    assert db.committed and out is p
    assert p.nombre_comercial == "Nuevo Nombre"


def test_404_si_no_existe():
    db = _FakeDB(results=[None])
    try:
        update_proyecto(999, ProyectoUpdate(sub_project="x"), db=db, _=None)
        assert False, "debió lanzar 404"
    except HTTPException as e:
        assert e.status_code == 404


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(fns)} tests pasaron.")
