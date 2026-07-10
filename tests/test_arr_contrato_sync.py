"""Sync bidireccional arr_proyectos <-> contratos_servicio (servicio_aplica='arriendo')."""
import pytest
from datetime import date
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
from app.models import Proyecto
from app.models.arriendos import ArrProyecto
from app.models.contratos import ContratoServicio
from app.services.arr_contrato_sync import (
    sync_arr_to_contrato, sync_contrato_to_arr,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, ArrProyecto.__table__, ContratoServicio.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _base(db):
    db.add(Proyecto(id=1, nombre_comercial="Minigranja La Puya", estado="en_operacion"))
    db.commit()


def test_sync_arr_to_contrato_crea_contrato(db):
    _base(db)
    arr = ArrProyecto(id=10, nombre="Minigranja La Puya", proyecto_id=1,
                      valor_base=1_000_000, fecha_firma_contrato=date(2025, 1, 1), activo=True)
    db.add(arr); db.commit()

    sync_arr_to_contrato(arr, db)

    c = db.query(ContratoServicio).filter_by(proyecto_id=1, servicio_aplica="arriendo").first()
    assert c is not None
    assert float(c.tarifa_base) == 1_000_000
    assert c.fecha_firma_contrato == date(2025, 1, 1)
    assert c.estado == "vigente"


def test_sync_arr_to_contrato_actualiza_existente(db):
    _base(db)
    db.add(ContratoServicio(id=5, proyecto_id=1, servicio_aplica="arriendo",
                            tarifa_base=1, estado="vigente"))
    arr = ArrProyecto(id=10, nombre="X", proyecto_id=1, valor_base=2_222, activo=True)
    db.add(arr); db.commit()

    sync_arr_to_contrato(arr, db)

    cs = db.query(ContratoServicio).filter_by(proyecto_id=1, servicio_aplica="arriendo").all()
    assert len(cs) == 1                     # no duplica
    assert float(cs[0].tarifa_base) == 2_222


def test_sync_arr_sin_proyecto_id_no_hace_nada(db):
    _base(db)
    arr = ArrProyecto(id=10, nombre="X", proyecto_id=None, valor_base=5, activo=True)
    db.add(arr); db.commit()
    sync_arr_to_contrato(arr, db)
    assert db.query(ContratoServicio).count() == 0


def test_sync_contrato_to_arr_escribe_de_vuelta(db):
    _base(db)
    arr = ArrProyecto(id=10, nombre="X", proyecto_id=1, valor_base=1, activo=True)
    c = ContratoServicio(id=5, proyecto_id=1, servicio_aplica="arriendo",
                         tarifa_base=9_999, fecha_firma_contrato=date(2026, 2, 2), estado="vigente")
    db.add_all([arr, c]); db.commit()

    sync_contrato_to_arr(c, db)

    assert float(db.query(ArrProyecto).get(10).valor_base) == 9_999
    assert db.query(ArrProyecto).get(10).fecha_firma_contrato == date(2026, 2, 2)
