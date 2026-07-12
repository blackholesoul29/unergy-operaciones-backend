"""Tests de las funciones puras del pipeline mensual de cumplimiento.

Cubren la agregación de energía (lecturas de frontera / generación diaria) y el
cálculo de cumplimiento + valores de liquidación, sin tocar la base de datos
(mismo estilo que el resto de la suite: datos simulados con SimpleNamespace).
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.pipeline_cumplimiento import (
    agregar_energia_lecturas_kwh,
    agregar_energia_generacion_kwh,
    calcular_valores_cumplimiento,
)


def _lec(fecha_hora, export):
    return SimpleNamespace(fecha_hora=fecha_hora, energia_activa_export_kwh=export)


def _gen(fecha, kwh):
    return SimpleNamespace(fecha=fecha, kwh_real=kwh)


# ── agregar_energia_lecturas_kwh ─────────────────────────────────────────────

def test_lecturas_suma_solo_el_mes_e_ignora_none():
    lecturas = [
        _lec(datetime(2026, 6, 5, 10), Decimal("100")),
        _lec(datetime(2026, 6, 20, 10), 50.5),
        _lec(datetime(2026, 6, 25, 10), None),      # None → ignorado (no es 0)
        _lec(datetime(2026, 7, 1, 10), 999),        # otro mes → fuera
        _lec(None, 5),                              # sin fecha → fuera
    ]
    assert agregar_energia_lecturas_kwh(lecturas, 2026, 6) == 150.5


def test_lecturas_sin_dato_devuelve_none():
    lecturas = [_lec(datetime(2026, 7, 1, 10), 10), _lec(datetime(2026, 6, 1, 10), None)]
    assert agregar_energia_lecturas_kwh(lecturas, 2026, 6) is None
    assert agregar_energia_lecturas_kwh([], 2026, 6) is None


# ── agregar_energia_generacion_kwh ───────────────────────────────────────────

def test_generacion_suma_solo_el_mes():
    gens = [
        _gen(date(2026, 6, 1), Decimal("30")),
        _gen(date(2026, 6, 2), 20),
        _gen(date(2026, 5, 31), 1000),   # mes anterior → fuera
        _gen(date(2026, 6, 3), None),    # None → ignorado
    ]
    assert agregar_energia_generacion_kwh(gens, 2026, 6) == 50.0


def test_generacion_sin_dato_devuelve_none():
    assert agregar_energia_generacion_kwh([], 2026, 6) is None
    assert agregar_energia_generacion_kwh([_gen(date(2026, 6, 1), None)], 2026, 6) is None


# ── calcular_valores_cumplimiento ────────────────────────────────────────────

def test_sin_compromisos():
    v = calcular_valores_cumplimiento(gen_kwh=120_000, min_mwh=None, max_mwh=None)
    assert v["estado_calc"] == "sin_compromisos"
    assert v["gen_total_mwh"] == 120.0
    assert v["compras_bolsa_mwh"] is None
    assert v["energia_facturable_kwh"] == 120_000.0


def test_deficit_calcula_compras_y_cop():
    # 80 MWh generados vs mínimo 100 MWh → 20 MWh de compras en bolsa.
    v = calcular_valores_cumplimiento(
        gen_kwh=80_000, min_mwh=100, max_mwh=150,
        tarifa_ppa_cop_kwh=300, precio_bolsa_cop_kwh=250,
    )
    assert v["estado_calc"] == "deficit"
    assert v["compras_bolsa_mwh"] == 20.0
    assert v["excedentes_bolsa_mwh"] == 0.0
    assert v["compras_bolsa_cop"] == 20 * 1000 * 250
    # Valoración = generación (MWh) * 1000 * tarifa (COP/kWh)
    assert v["valoracion_contrato_cop"] == 80 * 1000 * 300
    # Facturable capado al máximo (150 MWh) pero gen < max → toda la generación.
    assert v["energia_facturable_kwh"] == 80_000.0


def test_ok_dentro_del_rango():
    v = calcular_valores_cumplimiento(gen_kwh=120_000, min_mwh=100, max_mwh=150)
    assert v["estado_calc"] == "ok"
    assert v["compras_bolsa_mwh"] == 0.0
    assert v["excedentes_bolsa_mwh"] == 0.0


def test_excedente_sobre_el_maximo_y_facturable_capado():
    v = calcular_valores_cumplimiento(
        gen_kwh=170_000, min_mwh=100, max_mwh=150, precio_bolsa_cop_kwh=200,
    )
    assert v["estado_calc"] == "excedente"
    assert v["excedentes_bolsa_mwh"] == 20.0
    assert v["excedentes_bolsa_cop"] == 20 * 1000 * 200
    # Facturable capado al máximo contratado (150 MWh = 150.000 kWh).
    assert v["energia_facturable_kwh"] == 150_000.0


def test_gen_none_se_trata_como_cero():
    v = calcular_valores_cumplimiento(gen_kwh=None, min_mwh=100, max_mwh=150)
    assert v["gen_total_mwh"] == 0.0
    assert v["estado_calc"] == "deficit"
    assert v["compras_bolsa_mwh"] == 100.0


def test_max_ausente_usa_el_minimo_como_tope():
    # Sin máximo explícito, el tope es el mínimo: 130 > 100 → excedente de 30.
    v = calcular_valores_cumplimiento(gen_kwh=130_000, min_mwh=100, max_mwh=None)
    assert v["estado_calc"] == "excedente"
    assert v["excedentes_bolsa_mwh"] == 30.0
