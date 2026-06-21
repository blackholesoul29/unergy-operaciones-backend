"""Tests de _estimar_perdida_falla (estimación financiera de pérdida por falla)
y del contrato de schema `energia_perdida_kwh` (valor real ingresado por el usuario)."""
from datetime import date

from app.api.v1.fallas import _estimar_perdida_falla, _SOLAR_CAPACITY_FACTOR, _PRECIO_ENERGIA_COP_KWH
from app.schemas.fallas import FallaCreate, FallaUpdate, FallaOut


def test_zero_downtime_is_zero():
    assert _estimar_perdida_falla(990, 0) == (0.0, 0.0)


def test_no_potencia_is_zero():
    assert _estimar_perdida_falla(None, 10) == (0.0, 0.0)


def test_known_value_24h_downtime():
    # 24h downtime → solar_hours = 12 ; kwh = 990 * 0.18 * 12
    kwh, cop = _estimar_perdida_falla(990, 24)
    assert kwh == round(990 * _SOLAR_CAPACITY_FACTOR * 12, 3)
    assert cop == round(kwh * _PRECIO_ENERGIA_COP_KWH, 2)


def test_solar_hours_is_half_of_downtime():
    # 10h downtime → solar_hours = 5 (≈50% del downtime)
    kwh, _ = _estimar_perdida_falla(100, 10)
    assert kwh == round(100 * _SOLAR_CAPACITY_FACTOR * 5, 3)


# --- Contrato energia_perdida_kwh ---------------------------------------
# Regresión: el frontend (FallaForm/FallaDetalle/FallaDetailView + vistas de
# Operaciones) lee y ESCRIBE `energia_perdida_kwh` (valor real medido), distinto
# de `kwh_perdidos_estimado` (estimación automática de _estimar_perdida_falla).
# Antes de este fix el backend no tenía el campo en los schemas, así que
# `model_dump()` lo descartaba silenciosamente en create/update → pérdida de
# datos para los cálculos de PPA y liquidaciones. Estos tests fijan el contrato.

_BASE = dict(
    proyecto_id=1, estado_id=1, prioridad_id=1,
    descripcion="falla de prueba", fecha_identificacion=date(2026, 6, 21),
)


def test_create_persists_energia_perdida_kwh():
    dump = FallaCreate(**_BASE, energia_perdida_kwh=123.456).model_dump()
    assert dump["energia_perdida_kwh"] == 123.456


def test_update_sends_energia_perdida_kwh_when_set():
    # update usa exclude_unset → solo viaja lo que el usuario tocó.
    dump = FallaUpdate(energia_perdida_kwh=7.5).model_dump(exclude_unset=True)
    assert dump == {"energia_perdida_kwh": 7.5}


def test_energia_perdida_kwh_is_distinct_from_estimado():
    # Ambos coexisten: real (entrada) vs estimado (auto). No son el mismo campo.
    fields = FallaCreate.model_fields
    assert "energia_perdida_kwh" in fields
    assert "kwh_perdidos_estimado" in fields


def test_falla_out_exposes_energia_perdida_kwh():
    assert "energia_perdida_kwh" in FallaOut.model_fields
