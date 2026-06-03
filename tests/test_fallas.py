"""Tests de _estimar_perdida_falla (estimación financiera de pérdida por falla)."""
from app.api.v1.fallas import _estimar_perdida_falla, _SOLAR_CAPACITY_FACTOR, _PRECIO_ENERGIA_COP_KWH


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
