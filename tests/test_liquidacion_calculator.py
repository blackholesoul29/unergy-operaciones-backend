"""Tests del motor de cálculo de datos XM de liquidaciones (funciones puras)."""
import pytest
from app.services.liquidacion_calculator import (
    TarifaNoResuelta, calcular_xm, resolver_tarifa,
)


# ── resolver_tarifa ───────────────────────────────────────────────────────────

def test_ppa_con_tarifa_usa_la_tarifa_ppa():
    assert resolver_tarifa("ppa", tarifa_ppa=310.5, precio_bolsa=800.0) == (310.5, "ppa")


def test_ppa_sin_tarifa_cae_a_bolsa():
    # Mes sin tarifa cargada en ppa_tarifas → se liquida al precio de bolsa.
    assert resolver_tarifa("ppa", tarifa_ppa=None, precio_bolsa=800.0) == (800.0, "bolsa")


def test_tipo_venta_no_ppa_ignora_la_tarifa_ppa():
    # Aunque exista tarifa PPA, una liquidación en bolsa se paga a precio de bolsa.
    assert resolver_tarifa("bolsa", tarifa_ppa=310.5, precio_bolsa=800.0) == (800.0, "bolsa")


def test_sin_tarifa_ni_precio_de_bolsa_no_liquida():
    with pytest.raises(TarifaNoResuelta):
        resolver_tarifa("ppa", tarifa_ppa=None, precio_bolsa=None)


def test_tarifa_cero_no_cuenta_como_tarifa():
    # Liquidar energía a $0 sería un dato financiero silenciosamente incorrecto.
    with pytest.raises(TarifaNoResuelta):
        resolver_tarifa("ppa", tarifa_ppa=0.0, precio_bolsa=0.0)


# ── calcular_xm ───────────────────────────────────────────────────────────────

def test_calculo_ppa_conocido():
    # 12.500 kWh × 310,50 COP/kWh = 3.881.250 COP
    calc = calcular_xm(12_500.0, "ppa", tarifa_ppa=310.5, precio_bolsa=800.0)
    assert calc.valor_bruto_cop == 3_881_250.00
    assert calc.tarifa_kwh == 310.5
    assert calc.origen_tarifa == "ppa"
    assert calc.energia_kwh == 12_500.0


def test_calculo_bolsa_conocido():
    # 1.000,5 kWh × 742,25 COP/kWh = 742.621,125 → 742.621,12 COP.
    # round() de Python rompe el empate hacia el par (banker's rounding); se conserva
    # el comportamiento previo del endpoint. En COP la media centésima es inmaterial.
    calc = calcular_xm(1_000.5, "bolsa", tarifa_ppa=None, precio_bolsa=742.25)
    assert calc.valor_bruto_cop == 742_621.12
    assert calc.origen_tarifa == "bolsa"


def test_redondeos_alineados_con_columnas_numeric():
    # energia Numeric(14,3), tarifa Numeric(12,6): no deben desbordar la escala.
    calc = calcular_xm(1.23456789, "ppa", tarifa_ppa=1.23456789)
    assert calc.energia_kwh == 1.235
    assert calc.tarifa_kwh == 1.234568


def test_sin_tarifa_propaga_error():
    with pytest.raises(TarifaNoResuelta):
        calcular_xm(500.0, "ppa", tarifa_ppa=None, precio_bolsa=None)
