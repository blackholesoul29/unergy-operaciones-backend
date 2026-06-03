"""Tests de la serialización pura _build_cumplimiento_out (contrato de la API)."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.api.v1.cumplimiento import _build_cumplimiento_out


def _row(**kw):
    base = dict(
        id=1, contrato_ppa_id=2, proyecto_id=3, anio=2026, mes=6,
        gen_total_mwh=Decimal("100.5"), compromiso_mwh=Decimal("90"),
        compras_bolsa_mwh=None, excedentes_bolsa_mwh=None,
        precio_bolsa_promedio=Decimal("250.0"), compras_bolsa_cop=None,
        excedentes_bolsa_cop=None, estado="abierto",
        tarifa_ppa_cop_mwh=Decimal("300"), valoracion_contrato_cop=Decimal("1000"),
        liquidacion_id=None,
        contrato_ppa=SimpleNamespace(nombre_interno="C1", comprador_nombre="Terpel"),
        created_at=datetime(2026, 6, 1, 12, 0, 0), updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_full_row_serializes_decimals_to_float():
    out = _build_cumplimiento_out(_row())
    assert out["gen_total_mwh"] == 100.5 and isinstance(out["gen_total_mwh"], float)
    assert out["compromiso_mwh"] == 90.0
    assert out["contrato_nombre"] == "C1" and out["comprador_nombre"] == "Terpel"
    assert out["created_at"] == "2026-06-01T12:00:00"
    assert out["updated_at"] is None          # None datetime → None, no crash
    assert out["compras_bolsa_mwh"] is None    # None numeric → None


def test_no_contrato_yields_none_names():
    out = _build_cumplimiento_out(_row(contrato_ppa=None))
    assert out["contrato_nombre"] is None
    assert out["comprador_nombre"] is None


def test_all_numerics_none_do_not_crash():
    out = _build_cumplimiento_out(_row(
        gen_total_mwh=None, compromiso_mwh=None, precio_bolsa_promedio=None,
        tarifa_ppa_cop_mwh=None, valoracion_contrato_cop=None,
        compras_bolsa_cop=None, excedentes_bolsa_cop=None))
    assert out["gen_total_mwh"] is None and out["valoracion_contrato_cop"] is None
    assert out["estado"] == "abierto" and out["anio"] == 2026
