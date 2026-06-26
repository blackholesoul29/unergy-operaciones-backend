"""Tests de la lógica de negocio pura de la pre-liquidación."""
from app.services.settlement_automation_service import compute_datos_calculados


def test_compute_basic_revenue_and_deviation():
    datos = compute_datos_calculados(
        generacion_real_kwh=1000.0,
        horas_con_datos=24,
        precio_promedio_cop_kwh=250.0,
        generacion_esperada_kwh=800.0,
    )
    assert datos["generacion_real_kwh"] == 1000.0
    assert datos["ingreso_estimado_cop"] == 250000.0
    assert datos["desviacion_pct"] == 25.0  # (1000-800)/800*100
    assert datos["horas_con_datos"] == 24
    assert datos["fuente"] == "MEM/ASIC"
    assert datos["cumplimiento"] is None


def test_compute_without_price_yields_no_revenue():
    datos = compute_datos_calculados(
        generacion_real_kwh=500.0,
        horas_con_datos=12,
        precio_promedio_cop_kwh=None,
        generacion_esperada_kwh=None,
    )
    assert datos["ingreso_estimado_cop"] is None
    assert datos["desviacion_pct"] is None
    assert datos["generacion_esperada_kwh"] is None


def test_compute_zero_expected_does_not_divide():
    datos = compute_datos_calculados(
        generacion_real_kwh=100.0,
        horas_con_datos=4,
        precio_promedio_cop_kwh=100.0,
        generacion_esperada_kwh=0.0,
    )
    assert datos["desviacion_pct"] is None  # esperada 0 → no se divide
    assert datos["ingreso_estimado_cop"] == 10000.0


def test_compute_carries_cumplimiento_payload():
    cumplimiento = {"contrato_ppa_id": 7, "compromiso_mwh": 90.0, "estado": "pendiente"}
    datos = compute_datos_calculados(
        generacion_real_kwh=1.0, horas_con_datos=1,
        precio_promedio_cop_kwh=1.0, generacion_esperada_kwh=None,
        cumplimiento=cumplimiento,
    )
    assert datos["cumplimiento"] == cumplimiento
