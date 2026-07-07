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


# ── Etiquetas y mensajes de usuario (copy en español, sin tokens crudos) ──────
from app.utils.compliance_calculator import (  # noqa: E402
    ESTADO_LABELS,
    etiqueta_estado,
    mensaje_liquidacion,
)


def test_etiqueta_estado_conocido_y_desconocido():
    assert etiqueta_estado(CUMPLE) == "Liquidada"
    assert etiqueta_estado(SIN_PRECIO) == "Pendiente de precio"
    assert etiqueta_estado(NO_CUMPLE) == "No liquidada"
    # Estado desconocido degrada al token, no revienta.
    assert etiqueta_estado("otro") == "otro"
    assert etiqueta_estado(None) == ""


def test_mensaje_liquidada_incluye_valor_y_fuente_legible():
    r = calcular_liquidacion(100_000, 200, "bolsa_mes")
    msg = mensaje_liquidacion(r, 100_000, 2026, 6)
    assert "Promedio mensual de bolsa" in msg  # etiqueta legible, no "bolsa_mes"
    assert "20,000,000" in msg
    assert "bolsa_mes" not in msg  # nunca el token crudo


def test_mensaje_sin_precio_es_accionable_y_no_filtra_tokens():
    r = calcular_liquidacion(100_000, None, "sin_precio")
    assert r.estado_cumplimiento == SIN_PRECIO
    msg = mensaje_liquidacion(r, 100_000, 2026, 6)
    assert "no está publicado" in msg
    assert "06/2026" in msg
    assert "reintente" in msg.lower()
    # No debe filtrar llaves internas del resultado.
    assert "estado_cumplimiento=" not in msg
    assert "fuente_precio=" not in msg


def test_mensaje_bajo_umbral_menciona_umbral():
    r = calcular_liquidacion(500, 200, "bolsa_mes", umbral_kwh=1000)
    assert r.estado_cumplimiento == NO_CUMPLE
    msg = mensaje_liquidacion(r, 500, 2026, 6)
    assert "umbral" in msg.lower()
    assert "1,000 kWh" in msg


def test_mensaje_sin_generacion():
    r = calcular_liquidacion(0, 200, "bolsa_mes")
    msg = mensaje_liquidacion(r, 0, 2026, 6)
    assert "sin generación" in msg.lower()
    assert "06/2026" in msg


def test_estado_labels_cubre_todos_los_estados():
    assert set(ESTADO_LABELS) == {CUMPLE, NO_CUMPLE, SIN_PRECIO}
