"""Rediseño Task 6: al excluir un proyecto del mes se guarda un motivo_exclusion."""
import types
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.om import OMSeleccion
from app.api.v1 import om as api
from app.schemas.om import OMSeleccionGuardar, OMSeleccionItem


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)
PERIODO = "2026-06"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ContratoServicio.__table__, OMSeleccion.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_guardar_seleccion_persiste_motivo_exclusion(db):
    c = ContratoServicio(servicio_aplica="mantenimiento", prestador_nombre="P")
    db.add(c)
    db.flush()

    payload = OMSeleccionGuardar(items=[
        OMSeleccionItem(contrato_id=c.id, incluido=False, motivo_exclusion="en disputa"),
    ])
    api.guardar_seleccion(PERIODO, payload, db=db, _=ADMIN)

    sel = db.query(OMSeleccion).filter(
        OMSeleccion.contrato_id == c.id, OMSeleccion.periodo == PERIODO
    ).first()
    assert sel.incluido is False
    assert sel.motivo_exclusion == "en disputa"


def test_incluido_limpia_motivo(db):
    c = ContratoServicio(servicio_aplica="mantenimiento", prestador_nombre="P")
    db.add(c)
    db.flush()
    # excluir con motivo, luego re-incluir sin motivo
    api.guardar_seleccion(PERIODO, OMSeleccionGuardar(items=[
        OMSeleccionItem(contrato_id=c.id, incluido=False, motivo_exclusion="x")]), db=db, _=ADMIN)
    api.guardar_seleccion(PERIODO, OMSeleccionGuardar(items=[
        OMSeleccionItem(contrato_id=c.id, incluido=True)]), db=db, _=ADMIN)

    sel = db.query(OMSeleccion).filter(OMSeleccion.contrato_id == c.id).first()
    assert sel.incluido is True
    assert sel.motivo_exclusion is None
