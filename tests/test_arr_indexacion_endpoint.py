"""Endpoint GET /arriendos/indexacion/{contrato_id}: serie de indexación de un
contrato de arriendo, calculada desde fecha_firma_contrato (Fecha de contrato),
NO desde fecha_inicio_om (Arriendos ya no usa esa fecha para indexar)."""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.arriendos import ArrIPCTasa
from app.api.v1 import arriendos as api


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
        ContratoServicio.__table__, ArrIPCTasa.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_indexa_desde_fecha_firma_contrato_no_desde_fecha_inicio_om(db):
    fecha_a = date(2019, 3, 15)   # fecha_firma_contrato
    fecha_b = date(2021, 7, 1)    # fecha_inicio_om (no debe usarse)

    c = ContratoServicio(
        servicio_aplica="arriendo", prestador_nombre="P",
        tarifa_base=12_000_000,
        fecha_firma_contrato=fecha_a,
        fecha_inicio_om=fecha_b,
    )
    db.add(c)
    db.flush()

    resp = api.indexacion_contrato(c.id, db=db, _=None)

    assert resp.anual[0].anio == fecha_a.year
    assert resp.anual[0].anio != fecha_b.year


def test_contrato_de_mantenimiento_no_encontrado_como_arriendo(db):
    c = ContratoServicio(
        servicio_aplica="mantenimiento", prestador_nombre="P",
        tarifa_base=12_000_000,
        fecha_firma_contrato=date(2020, 1, 1),
    )
    db.add(c)
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        api.indexacion_contrato(c.id, db=db, _=None)

    assert exc_info.value.status_code == 404
