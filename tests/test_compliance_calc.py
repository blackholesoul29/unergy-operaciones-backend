"""Tests del cálculo de cumplimiento y liquidación automática.

Cubren la fórmula núcleo (energía × precio), los estados de cumplimiento y los
casos borde (generación cero/negativa, precio ausente/negativo, umbral). No
tocan la BD. El caso principal del plan de pruebas — 100 MWh a $200.000/MWh =
$20M — se expresa en unidades reales del sistema (kWh y COP/kWh):
100.000 kWh × 200 COP/kWh = 20.000.000 COP.
"""
from app.utils.compliance_calculator import (
    CUMPLE,
    NO_CUMPLE,
    SIN_PRECIO,
    ComplianceCalculator,
    calcular_liquidacion,
)
from app.utils.xm_price_mapper import FUENTE_MES, PrecioResuelto


def test_liquidacion_100mwh_por_200k_da_20millones():
    r = calcular_liquidacion(100_000, 200, "bolsa_mes")
    assert r.cumple is True
    assert r.estado_cumplimiento == CUMPLE
    assert r.valor_bruto_cop == 20_000_000.0
    assert r.precio_aplicado == 200.0
    assert r.fuente_precio == "bolsa_mes"


def test_generacion_cero_no_liquida():
    r = calcular_liquidacion(0, 200, "bolsa_mes")
    assert r.cumple is False
    assert r.estado_cumplimiento == NO_CUMPLE
    assert r.valor_bruto_cop == 0.0
    assert r.desglose["motivo"] == "sin_generacion"


def test_generacion_negativa_no_liquida():
    r = calcular_liquidacion(-50, 200, "bolsa_mes")
    assert r.cumple is False
    assert r.valor_bruto_cop == 0.0


def test_precio_ausente_marca_sin_precio():
    r = calcular_liquidacion(100_000, None, "sin_precio")
    assert r.cumple is True  # hubo generación
    assert r.estado_cumplimiento == SIN_PRECIO
    assert r.valor_bruto_cop == 0.0
    assert r.precio_aplicado is None


def test_precio_negativo_no_liquida():
    r = calcular_liquidacion(100_000, -10, "bolsa_mes")
    assert r.estado_cumplimiento == SIN_PRECIO
    assert r.valor_bruto_cop == 0.0


def test_umbral_de_cumplimiento_no_alcanzado():
    r = calcular_liquidacion(500, 200, "bolsa_mes", umbral_kwh=1000)
    assert r.cumple is False
    assert r.estado_cumplimiento == NO_CUMPLE
    assert r.desglose["motivo"] == "bajo_umbral"


def test_umbral_alcanzado_liquida():
    r = calcular_liquidacion(2000, 200, "bolsa_mes", umbral_kwh=1000)
    assert r.cumple is True
    assert r.valor_bruto_cop == 400_000.0


# ── ComplianceCalculator con mapper simulado ─────────────────────────────────
class FakeMapper:
    def __init__(self, precio, fuente):
        self._pr = PrecioResuelto(precio, fuente)

    def get_month_average(self, year, month, plant_id=None):
        return self._pr

    def get_price_for_date(self, fecha, plant_id=None):
        return self._pr


def test_calculator_evaluar_mes_integra_mapper():
    calc = ComplianceCalculator(FakeMapper(200, FUENTE_MES))
    r = calc.evaluar_mes(100_000, 2026, 6)
    assert r.valor_bruto_cop == 20_000_000.0
    assert r.fuente_precio == FUENTE_MES


def test_calculator_evaluar_dia_integra_mapper():
    calc = ComplianceCalculator(FakeMapper(210, "bolsa_diario"))
    r = calc.evaluar_dia(1000, "2026-06-15")
    assert r.valor_bruto_cop == 210_000.0
    assert r.fuente_precio == "bolsa_diario"
