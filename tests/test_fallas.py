"""Tests de _estimar_perdida_falla (estimación financiera de pérdida por falla)
y validación del campo sla_limite_horas en los esquemas de Falla."""
import pytest
from datetime import date
from pydantic import ValidationError
from app.api.v1.fallas import _estimar_perdida_falla, _SOLAR_CAPACITY_FACTOR, _PRECIO_ENERGIA_COP_KWH
from app.schemas.fallas import FallaCreate, FallaUpdate


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


def _falla_create_kwargs(**overrides):
    base = dict(
        proyecto_id=1,
        estado_id=1,
        prioridad_id=1,
        descripcion="x",
        fecha_identificacion=date(2026, 1, 1),
    )
    base.update(overrides)
    return base


def test_create_accepts_valid_sla_limite_horas():
    falla = FallaCreate(**_falla_create_kwargs(sla_limite_horas=48))
    assert falla.sla_limite_horas == 48


def test_create_allows_null_sla_limite_horas():
    falla = FallaCreate(**_falla_create_kwargs())
    assert falla.sla_limite_horas is None


def test_create_rejects_negative_sla_limite_horas():
    with pytest.raises(ValidationError):
        FallaCreate(**_falla_create_kwargs(sla_limite_horas=-1))


def test_update_rejects_negative_sla_limite_horas():
    with pytest.raises(ValidationError):
        FallaUpdate(sla_limite_horas=-5)


def test_update_accepts_zero_sla_limite_horas():
    assert FallaUpdate(sla_limite_horas=0).sla_limite_horas == 0
