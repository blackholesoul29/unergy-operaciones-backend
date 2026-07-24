"""Diagnóstico read-only de migración ArrProyecto → contrato de arriendo."""
import types
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.arriendos import ArrProyecto
from app.models.proyectos import Proyecto
from app.models.contratos import ContratoServicio
from app.api.v1 import arriendos as api


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ArrProyecto.__table__, Proyecto.__table__, ContratoServicio.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_diagnostico_cuenta_con_sin_contrato_y_sin_match(db):
    # Alpha: tiene proyecto + contrato arriendo
    pa = Proyecto(nombre_comercial="Alpha", estado="en_operacion"); db.add(pa); db.flush()
    db.add(ContratoServicio(servicio_aplica="arriendo", proyecto_id=pa.id, estado="vigente"))
    db.add(ArrProyecto(nombre="Alpha", activo=True))
    # Bravo: tiene proyecto pero NO contrato arriendo
    pb = Proyecto(nombre_comercial="Bravo", estado="en_operacion"); db.add(pb); db.flush()
    db.add(ArrProyecto(nombre="Bravo", activo=True))
    # Charlie: ArrProyecto sin proyecto que haga match
    db.add(ArrProyecto(nombre="Charlie", activo=True))
    db.flush()

    r = api.diagnostico_migracion(db=db, _=ADMIN)
    assert r["total_arr_proyectos"] == 3
    assert r["con_contrato_arriendo"] == 1
    assert r["sin_contrato_arriendo"] == 1
    assert any("Bravo" in x for x in r["ejemplos_sin_contrato"])
    assert r["sin_match_de_proyecto"] == 1 and "Charlie" in r["ejemplos_sin_match"]
