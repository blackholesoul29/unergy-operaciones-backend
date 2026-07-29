"""Backfill: ArrDocumento existentes con arr_proyecto_id pero sin proyecto_id
se enlazan al Proyecto correspondiente (vía match difuso ArrProyecto->Proyecto,
mismo mecanismo ya usado en el resto del módulo). Fill-if-null, no pisa nada."""
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
from app.main import _backfill_arr_documento_proyecto_id


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


def test_backfill_enlaza_documento_existente(db):
    p = Proyecto(nombre_comercial="MGS Test")
    db.add(p); db.flush()
    ap = ArrProyecto(nombre="MGS Test", activo=True)
    db.add(ap); db.flush()
    doc = ArrDocumento(
        arr_proyecto_id=ap.id, periodo="2026-07", pago_id=1,
        codigo_contrato="C-1", tipo_documento="cuenta_cobro",
        nombre_archivo="a.pdf", ruta_local="/x/a.pdf",
    )
    db.add(doc); db.flush()

    _backfill_arr_documento_proyecto_id(db)

    db.refresh(doc)
    assert doc.proyecto_id == p.id


def test_backfill_no_pisa_si_ya_esta_enlazado(db):
    p1 = Proyecto(nombre_comercial="MGS Test 2")
    p2 = Proyecto(nombre_comercial="MGS Test 3")
    db.add_all([p1, p2]); db.flush()
    ap = ArrProyecto(nombre="MGS Test 2", activo=True)
    db.add(ap); db.flush()
    doc = ArrDocumento(
        arr_proyecto_id=ap.id, periodo="2026-07", pago_id=1,
        codigo_contrato="C-2", tipo_documento="cuenta_cobro",
        nombre_archivo="b.pdf", ruta_local="/x/b.pdf",
        proyecto_id=p2.id,
    )
    db.add(doc); db.flush()

    _backfill_arr_documento_proyecto_id(db)

    db.refresh(doc)
    assert doc.proyecto_id == p2.id
