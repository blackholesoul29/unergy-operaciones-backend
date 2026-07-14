"""Valoración del déficit PPA: penalidad contractual vs. precio de bolsa.

El impacto se estimaba siempre a bolsa. Ahora `tipo_precio_referencia` del
contrato decide, y la trampa es de UNIDADES: la penalidad va en COP/MWh y la
bolsa en COP/kWh (~1000x más chica en crudo). Comparar sin normalizar haría que
la penalidad "gane" siempre — hay un test dedicado a eso.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.contratos import PPAContrato
from app.models.proyectos import Proyecto
from app.models.cumplimiento import CumplimientoMensual
from app.api.v1 import alertas as alertas_api
from app.services.cumplimiento_service import calcular_impacto_deficit


def _contrato(penalidad=None, tipo="HIBRIDO"):
    return SimpleNamespace(precio_penalidad_mwh=penalidad, tipo_precio_referencia=tipo)


# Bolsa 250 COP/kWh = 250_000 COP/MWh.
BOLSA_KWH = 250.0
BOLSA_MWH = 250_000.0


# --- HIBRIDO: manda el precio más alto (normalizado a COP/MWh) --------------

def test_hibrido_penalidad_mas_cara_que_bolsa():
    imp = calcular_impacto_deficit(10, _contrato(penalidad=400_000), BOLSA_KWH)
    assert imp.precio_aplicado_mwh == 400_000
    assert imp.fuente_precio == "PENALIDAD_CONTRACTUAL"
    assert imp.impacto_cop == 4_000_000


def test_hibrido_bolsa_mas_cara_que_penalidad():
    """Penalidad 100.000 COP/MWh < bolsa 250.000 COP/MWh → manda la bolsa."""
    imp = calcular_impacto_deficit(10, _contrato(penalidad=100_000), BOLSA_KWH)
    assert imp.precio_aplicado_mwh == BOLSA_MWH
    assert imp.fuente_precio == "BOLSA"
    assert imp.impacto_cop == 2_500_000


def test_hibrido_no_confunde_cop_por_mwh_con_cop_por_kwh():
    """Regresión de unidades: comparar 100.000 (COP/MWh) contra 250 (COP/kWh)
    crudos elegiría la penalidad por ser 400x más grande en número, cuando en
    realidad la bolsa es 2.5x más cara. La bolsa debe ganar."""
    imp = calcular_impacto_deficit(10, _contrato(penalidad=100_000), BOLSA_KWH)
    assert imp.fuente_precio == "BOLSA", "penalidad COP/MWh comparada sin normalizar"


def test_hibrido_sin_penalidad_cae_a_bolsa():
    imp = calcular_impacto_deficit(10, _contrato(penalidad=None), BOLSA_KWH)
    assert imp.fuente_precio == "BOLSA"
    assert imp.impacto_cop == 2_500_000


def test_hibrido_sin_bolsa_usa_penalidad():
    imp = calcular_impacto_deficit(10, _contrato(penalidad=400_000), None)
    assert imp.fuente_precio == "PENALIDAD_CONTRACTUAL"
    assert imp.impacto_cop == 4_000_000


# --- PENALIDAD_CONTRACTUAL --------------------------------------------------

def test_penalidad_contractual_ignora_bolsa_mas_cara():
    imp = calcular_impacto_deficit(
        10, _contrato(penalidad=100_000, tipo="PENALIDAD_CONTRACTUAL"), BOLSA_KWH,
    )
    assert imp.precio_aplicado_mwh == 100_000
    assert imp.fuente_precio == "PENALIDAD_CONTRACTUAL"
    assert imp.impacto_cop == 1_000_000


def test_penalidad_contractual_sin_penalidad_cae_a_bolsa():
    """Contrato marcado como penalidad pero sin el valor cargado: no se queda
    sin estimación, cae a bolsa y lo declara."""
    imp = calcular_impacto_deficit(
        10, _contrato(penalidad=None, tipo="PENALIDAD_CONTRACTUAL"), BOLSA_KWH,
    )
    assert imp.fuente_precio == "BOLSA"
    assert imp.impacto_cop == 2_500_000


# --- PRECIO_BOLSA -----------------------------------------------------------

def test_precio_bolsa_ignora_penalidad_mas_cara():
    imp = calcular_impacto_deficit(
        10, _contrato(penalidad=999_999, tipo="PRECIO_BOLSA"), BOLSA_KWH,
    )
    assert imp.precio_aplicado_mwh == BOLSA_MWH
    assert imp.fuente_precio == "BOLSA"
    assert imp.impacto_cop == 2_500_000


def test_precio_bolsa_sin_bolsa_no_estima():
    imp = calcular_impacto_deficit(
        10, _contrato(penalidad=400_000, tipo="PRECIO_BOLSA"), None,
    )
    assert imp.impacto_cop is None and imp.fuente_precio is None


# --- Bordes -----------------------------------------------------------------

def test_sin_ningun_precio_no_inventa_impacto():
    imp = calcular_impacto_deficit(10, _contrato(), None)
    assert imp == type(imp)(None, None, None)


def test_deficit_none_no_estima():
    imp = calcular_impacto_deficit(None, _contrato(penalidad=400_000), BOLSA_KWH)
    assert imp.impacto_cop is None


def test_acepta_decimal_de_sqlalchemy():
    """Numeric llega como Decimal: no debe reventar al mezclarlo con float."""
    imp = calcular_impacto_deficit(
        10.0, _contrato(penalidad=Decimal("400000.00")), Decimal("250.0"),
    )
    assert imp.impacto_cop == 4_000_000


def test_tipo_desconocido_se_comporta_como_hibrido():
    """La columna no tiene CHECK: basura en BD no debe tumbar la alerta."""
    imp = calcular_impacto_deficit(10, _contrato(penalidad=400_000, tipo="BASURA"), BOLSA_KWH)
    assert imp.fuente_precio == "PENALIDAD_CONTRACTUAL"


def test_contrato_por_defecto_replica_la_formula_vieja():
    """Compatibilidad: sin penalidad cargada, el impacto es el de antes
    (deficit_mwh * 1000 * precio_bolsa_cop_kwh)."""
    deficit, precio_kwh = 12.5, 300.0
    imp = calcular_impacto_deficit(deficit, _contrato(), precio_kwh)
    assert imp.impacto_cop == round(deficit * 1000 * precio_kwh, 0)


# --- Integración: la alerta ya sale valorada con el precio del contrato ------

@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, PPAContrato.__table__, CumplimientoMensual.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _alerta(db, **contrato_kw):
    """Un contrato en déficit (50 de 100 MWh) y su alerta."""
    c = PPAContrato(id=1, nombre_interno="PPA Test", **contrato_kw)
    db.add(c)
    db.add(CumplimientoMensual(
        id=1, contrato_ppa_id=1, anio=2026, mes=6,
        gen_total_mwh=50, compromiso_mwh=100, precio_bolsa_promedio=BOLSA_KWH,
    ))
    db.commit()
    res = alertas_api.alertas_cumplimiento_ppa(
        anio=2026, mes=6, umbral_pct=90.0, db=db, _=None,
    )
    assert res["total_alertas"] == 1
    return res["alertas"][0]


def test_alerta_usa_penalidad_cuando_supera_la_bolsa(db):
    a = _alerta(db, precio_penalidad_mwh=400_000, tipo_precio_referencia="HIBRIDO")
    assert a["fuente_precio"] == "PENALIDAD_CONTRACTUAL"
    assert a["precio_aplicado_mwh"] == 400_000
    assert a["impacto_estimado_cop"] == 50 * 400_000
    assert "penalidad contractual" in a["mensaje"]


def test_alerta_sin_penalidad_mantiene_la_valoracion_a_bolsa(db):
    a = _alerta(db, tipo_precio_referencia="HIBRIDO")
    assert a["fuente_precio"] == "BOLSA"
    assert a["impacto_estimado_cop"] == 50 * 1000 * BOLSA_KWH  # fórmula histórica
    assert a["precio_bolsa_promedio"] == BOLSA_KWH  # el crudo COP/kWh sigue expuesto
