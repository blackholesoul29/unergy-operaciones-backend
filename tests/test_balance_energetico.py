"""Tests del builder puro _build_balance_item (contrato con la vista MEM/BalanceView).

La vista de balance energético del frontend consume campos con nombres
semánticos (generacion_real, compromiso, precio_bolsa, contrato_nombre,
proyecto_nombre). Estos tests fijan ese contrato y verifican los cálculos
derivados (balance neto e impacto financiero) sin tocar la base de datos,
igual que test_cumplimiento.py.
"""
from decimal import Decimal
from types import SimpleNamespace

from app.api.v1.cumplimiento import _build_balance_item


def _row(**kw):
    base = dict(
        contrato_ppa_id=2,
        proyecto_id=3,
        anio=2026,
        mes=6,
        gen_total_mwh=Decimal("100.5"),
        compromiso_mwh=Decimal("90"),
        compras_bolsa_mwh=Decimal("5"),
        excedentes_bolsa_mwh=Decimal("15.5"),
        precio_bolsa_promedio=Decimal("250.0"),
        estado="cerrado",
        contrato_ppa=SimpleNamespace(nombre_interno="C1", comprador_nombre="Terpel"),
        proyecto=SimpleNamespace(nombre_comercial="Planta Sol"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_full_row_maps_frontend_field_names():
    out = _build_balance_item(_row())
    # Nombres exactos que lee BalanceView.vue
    assert out["contrato_nombre"] == "C1"
    assert out["comprador_nombre"] == "Terpel"
    assert out["proyecto_nombre"] == "Planta Sol"
    assert out["generacion_real"] == 100.5 and isinstance(out["generacion_real"], float)
    assert out["compromiso"] == 90.0
    assert out["precio_bolsa"] == 250.0
    assert out["compras_bolsa_mwh"] == 5.0
    assert out["excedentes_bolsa_mwh"] == 15.5
    assert out["estado"] == "cerrado"


def test_balance_neto_and_impacto_are_derived():
    out = _build_balance_item(_row())
    # balance neto = generación real − compromiso (MWh)
    assert out["balance_net"] == 10.5
    # impacto = balance (MWh) × 1000 (kWh/MWh) × precio (COP/kWh) = COP
    assert out["impacto_financiero"] == 10.5 * 1000 * 250.0


def test_deficit_yields_negative_balance_and_impacto():
    out = _build_balance_item(_row(gen_total_mwh=Decimal("80"), compromiso_mwh=Decimal("90")))
    assert out["balance_net"] == -10.0
    assert out["impacto_financiero"] == -10.0 * 1000 * 250.0


def test_null_row_price_falls_back_to_month_market_avg():
    # Sin precio por fila → usa el precio de bolsa promedio del mes (COP/kWh)
    out = _build_balance_item(_row(precio_bolsa_promedio=None), precio_mercado_cop_kwh=300.0)
    assert out["precio_bolsa"] == 300.0
    assert out["impacto_financiero"] == 10.5 * 1000 * 300.0


def test_none_numerics_default_to_zero_no_crash():
    out = _build_balance_item(_row(
        gen_total_mwh=None, compromiso_mwh=None, precio_bolsa_promedio=None,
        compras_bolsa_mwh=None, excedentes_bolsa_mwh=None))
    assert out["generacion_real"] == 0.0
    assert out["compromiso"] == 0.0
    assert out["precio_bolsa"] == 0.0  # sin fallback de mercado → 0.0
    assert out["balance_net"] == 0.0
    assert out["impacto_financiero"] == 0.0
    assert out["compras_bolsa_mwh"] == 0.0


def test_missing_contrato_and_proyecto_yield_none_names():
    out = _build_balance_item(_row(contrato_ppa=None, proyecto=None))
    assert out["contrato_nombre"] is None
    assert out["comprador_nombre"] is None
    assert out["proyecto_nombre"] is None
    # Los numéricos siguen presentes aunque falten las relaciones
    assert out["generacion_real"] == 100.5
