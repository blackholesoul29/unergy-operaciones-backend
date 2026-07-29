"""Backfill: ArrSeleccion/ArrDocumento existentes sin arr_arrendador_id se
enlazan al (único, en ese momento) arrendador del contrato del proyecto
emparejado. Fill-if-null, no pisa lo ya enlazado."""
from datetime import date
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.proyectos import Proyecto
from app.models.arriendos import ArrProyecto, ArrArrendador, ArrSeleccion, ArrDocumento
from app.main import _backfill_arr_arrendador_id


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ContratoServicio.__table__, Proyecto.__table__, ArrProyecto.__table__,
        ArrArrendador.__table__, ArrSeleccion.__table__, ArrDocumento.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_backfill_enlaza_seleccion_existente(db):
    p = Proyecto(nombre_comercial="MGS Test")
    db.add(p); db.flush()
    c = ContratoServicio(servicio_aplica="arriendo", proyecto_id=p.id, prestador_nombre="Juan")
    db.add(c); db.flush()
    arr = ArrArrendador(contrato_id=c.id, nombre="Juan", valor_base=1_000_000)
    db.add(arr); db.flush()
    ap = ArrProyecto(nombre="MGS Test", activo=True)
    db.add(ap); db.flush()
    sel = ArrSeleccion(arr_proyecto_id=ap.id, periodo="2026-07", incluido=True, facturado=False)
    db.add(sel); db.flush()

    _backfill_arr_arrendador_id(db)

    db.refresh(sel)
    assert sel.arr_arrendador_id == arr.id


def test_backfill_no_pisa_si_ya_esta_enlazado(db):
    p = Proyecto(nombre_comercial="MGS Test 2")
    db.add(p); db.flush()
    c = ContratoServicio(servicio_aplica="arriendo", proyecto_id=p.id)
    db.add(c); db.flush()
    arr1 = ArrArrendador(contrato_id=c.id, nombre="Uno", valor_base=1)
    arr2 = ArrArrendador(contrato_id=c.id, nombre="Dos", valor_base=2)
    db.add_all([arr1, arr2]); db.flush()
    ap = ArrProyecto(nombre="MGS Test 2", activo=True)
    db.add(ap); db.flush()
    sel = ArrSeleccion(arr_proyecto_id=ap.id, periodo="2026-07", incluido=True, facturado=False,
                        arr_arrendador_id=arr2.id)
    db.add(sel); db.flush()

    _backfill_arr_arrendador_id(db)

    db.refresh(sel)
    assert sel.arr_arrendador_id == arr2.id
