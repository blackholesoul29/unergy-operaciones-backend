"""Rediseño Task 2: el panel O&M solo lista contratos de mantenimiento cuyo
proyecto esté 'en_operacion' (harness sqlite)."""
import types
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401 - registra modelos/relationships
from app.models.contratos import ContratoServicio
from app.models.proyectos import Proyecto
from app.api.v1 import om as api


@compiles(JSONB, "sqlite")
def _jsonb(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__, ContratoServicio.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_listar_contratos_om_solo_en_operacion(db):
    op = Proyecto(nombre_comercial="Op", estado="en_operacion")
    des = Proyecto(nombre_comercial="Des", estado="en_desarrollo")
    db.add_all([op, des])
    db.flush()
    db.add(ContratoServicio(servicio_aplica="mantenimiento", proyecto_id=op.id))
    db.add(ContratoServicio(servicio_aplica="mantenimiento", proyecto_id=des.id))
    db.add(ContratoServicio(servicio_aplica="mantenimiento", proyecto_id=None))  # sin proyecto
    db.flush()

    nombres = {r.nombre_proyecto for r in api.listar_contratos_om(db=db, _=ADMIN)}
    assert "Op" in nombres
    assert "Des" not in nombres          # en_desarrollo excluido
    assert len(nombres) == 1             # el sin-proyecto también queda fuera
