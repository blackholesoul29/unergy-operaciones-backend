"""Aprobación de una pre-liquidación: el número que el revisor aprobó debe quedar
PERSISTIDO en la `Liquidacion` final (antes quedaba NULL → handoff roto), y una
estimación de ingreso DESCONOCIDO no se puede aprobar en silencio.
"""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from fastapi import HTTPException

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.proyectos import Proyecto
from app.models.liquidaciones import Liquidacion, LiquidacionXMDato
from app.models.mem import LiquidacionPreliminar
from app.api.v1 import liquidaciones as liq_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):  # JSONB es de PG; en SQLite → TEXT
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):  # SQLite solo autoincrementa INTEGER
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__,
            Liquidacion.__table__,
            LiquidacionXMDato.__table__,
            LiquidacionPreliminar.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_USUARIO = types.SimpleNamespace(id=1)


def _make_prelim(db, datos):
    p = Proyecto(nombre_comercial="Planta X", estado="en_operacion")
    db.add(p)
    db.flush()
    prelim = LiquidacionPreliminar(
        proyecto_id=p.id,
        periodo=date(2026, 6, 1),
        estado="pendiente_revision",
        datos_calculados=datos,
    )
    db.add(prelim)
    db.flush()
    return prelim


def test_approve_persists_revenue_and_xm_detail(db):
    prelim = _make_prelim(db, {
        "ingreso_estimado_cop": 250000.0,
        "generacion_valorizada_kwh": 1000.0,
        "precio_bolsa_ponderado_cop_kwh": 250.0,
        "estado_cobertura": "completa",
        "cobertura_precio_pct": 100.0,
    })

    out = liq_api.approve_preliminar(prelim.id, db=db, usuario=_USUARIO)

    liq = db.query(Liquidacion).filter(Liquidacion.id == out["liquidacion_id"]).first()
    assert liq is not None
    # El ingreso aprobado quedó PERSISTIDO (antes era NULL).
    assert float(liq.ingresos_energia_cop) == 250000.0
    # Detalle XM auditable.
    xm = db.query(LiquidacionXMDato).filter(LiquidacionXMDato.liquidacion_id == liq.id).all()
    assert len(xm) == 1
    assert float(xm[0].energia_kwh) == 1000.0
    assert float(xm[0].tarifa_aplicada_kwh) == 250.0
    assert float(xm[0].valor_bruto_cop) == 250000.0
    # La pre-liquidación quedó aprobada y vinculada.
    db.refresh(prelim)
    assert prelim.estado == "aprobada"
    assert prelim.liquidacion_id == liq.id


def test_approve_blocks_unknown_revenue(db):
    prelim = _make_prelim(db, {
        "ingreso_estimado_cop": None,
        "generacion_valorizada_kwh": 0.0,
        "precio_bolsa_ponderado_cop_kwh": None,
        "estado_cobertura": "sin_precio",
        "cobertura_precio_pct": 0.0,
    })

    with pytest.raises(HTTPException) as exc:
        liq_api.approve_preliminar(prelim.id, db=db, usuario=_USUARIO)
    assert exc.value.status_code == 409
    # No se creó liquidación y la pre-liquidación sigue pendiente.
    assert db.query(Liquidacion).count() == 0
    db.refresh(prelim)
    assert prelim.estado == "pendiente_revision"


def test_approve_is_idempotent(db):
    prelim = _make_prelim(db, {
        "ingreso_estimado_cop": 100.0,
        "generacion_valorizada_kwh": 1.0,
        "precio_bolsa_ponderado_cop_kwh": 100.0,
        "estado_cobertura": "completa",
        "cobertura_precio_pct": 100.0,
    })
    first = liq_api.approve_preliminar(prelim.id, db=db, usuario=_USUARIO)
    second = liq_api.approve_preliminar(prelim.id, db=db, usuario=_USUARIO)
    assert first["liquidacion_id"] == second["liquidacion_id"]
    # No se duplicó el detalle XM.
    assert db.query(LiquidacionXMDato).count() == 1
