"""Tests del cálculo de impacto de mantenimiento (funciones puras).

Cubren el núcleo `compute_metrics` (energía perdida = esperada − real, impacto
económico = perdida × precio, bandera de penalización PPA) y la propiedad
`duration_hours` del modelo. No tocan la BD.
"""
from datetime import datetime, timezone, timedelta

from app.services.impact_calculator import compute_metrics, PRECIO_ENERGIA_COP_KWH
from app.models.mantenimiento_impacto import MantenimientoImpacto

_COL_TZ = timezone(timedelta(hours=-5))


def test_lost_energy_es_esperada_menos_real():
    m = compute_metrics(1000.0, 300.0)
    assert m["lost_energy_kwh"] == 700.0
    # impacto económico = perdida × precio de referencia
    assert m["financial_impact_cop"] == round(700.0 * PRECIO_ENERGIA_COP_KWH, 2)
    assert m["ppa_penalty_risk_flag"] is True


def test_downtime_total_real_ausente_asume_cero():
    m = compute_metrics(500.0, None)
    assert m["lost_energy_kwh"] == 500.0
    assert m["ppa_penalty_risk_flag"] is True


def test_sin_perdida_cuando_real_supera_esperada():
    m = compute_metrics(200.0, 250.0)
    assert m["lost_energy_kwh"] == 0.0
    assert m["financial_impact_cop"] == 0.0
    assert m["ppa_penalty_risk_flag"] is False


def test_esperada_ausente_no_calcula():
    m = compute_metrics(None, 100.0)
    assert m["lost_energy_kwh"] is None
    assert m["financial_impact_cop"] is None
    assert m["ppa_penalty_risk_flag"] is False


def test_precio_personalizado():
    m = compute_metrics(100.0, 0.0, precio_cop_kwh=1200.0)
    assert m["financial_impact_cop"] == 120000.0


def test_duration_hours_hybrid():
    m = MantenimientoImpacto(
        proyecto_id=1,
        start_time=datetime(2026, 7, 1, 8, 0, tzinfo=_COL_TZ),
        end_time=datetime(2026, 7, 1, 14, 30, tzinfo=_COL_TZ),
    )
    assert m.duration_hours == 6.5


def test_duration_hours_end_antes_de_start_no_negativa():
    m = MantenimientoImpacto(
        proyecto_id=1,
        start_time=datetime(2026, 7, 1, 14, 0, tzinfo=_COL_TZ),
        end_time=datetime(2026, 7, 1, 8, 0, tzinfo=_COL_TZ),
    )
    assert m.duration_hours == 0.0
