"""Tests del motor de liquidación XM.

Siguen el patrón del repo: prueban las funciones PURAS (cálculo, período) y la
validación de schemas / orden de rutas, sin tocar la base de datos.
"""
from datetime import date

import pytest

from app.services.liquidacion_engine import calcular_diferencia_y_valor
from app.cron_jobs.liquidacion_scheduler import periodo_anterior


# ── Cálculo puro ────────────────────────────────────────────────────────────────

def test_excedente_da_diferencia_y_valor_positivos():
    # Generó 120 MWh, comprometió 100 → excedente de 20 MWh a 250.000 COP/MWh.
    dif, valor = calcular_diferencia_y_valor(120.0, 100.0, 250_000.0)
    assert dif == 20.0
    assert valor == 5_000_000.0


def test_deficit_da_diferencia_y_valor_negativos():
    # Generó 80 MWh, comprometió 100 → déficit de 20 MWh (costo de compra bolsa).
    dif, valor = calcular_diferencia_y_valor(80.0, 100.0, 250_000.0)
    assert dif == -20.0
    assert valor == -5_000_000.0


def test_sin_compromiso_liquida_toda_la_generacion():
    dif, valor = calcular_diferencia_y_valor(50.0, 0.0, 300_000.0)
    assert dif == 50.0
    assert valor == 15_000_000.0


def test_redondeo_mwh_y_cop():
    dif, valor = calcular_diferencia_y_valor(100.123456, 100.0, 199_999.0)
    assert dif == 0.1235                      # 4 decimales (MWh)
    assert valor == round(0.1235 * 199_999.0, 2)  # 2 decimales (COP)


# ── Período anterior (cron) ─────────────────────────────────────────────────────

def test_periodo_anterior_mes_normal():
    assert periodo_anterior(date(2026, 7, 11)) == (2026, 6)


def test_periodo_anterior_enero_rueda_al_anio_previo():
    assert periodo_anterior(date(2026, 1, 5)) == (2025, 12)


# ── Validación de schemas ────────────────────────────────────────────────────────

def test_trigger_request_valido():
    from app.schemas.liquidacion import LiquidacionTriggerRequest
    req = LiquidacionTriggerRequest(proyecto_id=3, mes=6, anio=2026)
    assert req.mes == 6


def test_trigger_request_mes_invalido():
    from pydantic import ValidationError
    from app.schemas.liquidacion import LiquidacionTriggerRequest
    with pytest.raises(ValidationError):
        LiquidacionTriggerRequest(proyecto_id=3, mes=13, anio=2026)


def test_create_estado_invalido_rechazado():
    from pydantic import ValidationError
    from app.schemas.liquidacion import LiquidacionCreate
    with pytest.raises(ValidationError):
        LiquidacionCreate(
            proyecto_id=1, periodo=date(2026, 6, 1),
            generacion_real=10, compromiso_ppa=5, precio_xm_promedio=1000,
            diferencia_mwh=5, valor_liquidacion=5000, estado="inventado",
        )


# ── Orden de rutas (motor antes de /{id}) ────────────────────────────────────────

def test_rutas_motor_antes_de_id():
    """Las rutas del motor tienen segmento literal 'motor' y deben registrarse
    ANTES de /{id}, o Starlette las intercepta (mismo bug histórico de /resumen)."""
    from app.api.v1.liquidaciones import router
    paths = [r.path for r in router.routes]
    i_id = paths.index("/liquidaciones/{id}")
    assert paths.index("/liquidaciones/motor/trigger-calculation") < i_id
    assert paths.index("/liquidaciones/motor/{proyecto_id}/periodo/{mes}/{anio}") < i_id
