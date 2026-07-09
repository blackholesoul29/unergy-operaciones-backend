"""Tests de las funciones puras del Balance Energético (sin base de datos)."""
from datetime import date

from app.api.v1.balance import (
    _iter_periods,
    _superavit_y_estado,
    _proyeccion_fin_anio,
    build_balance,
)


# ── _iter_periods ─────────────────────────────────────────────────────────────

def test_iter_periods_full_year():
    periods = _iter_periods(date(2026, 1, 1), date(2026, 12, 31))
    assert periods[0] == (2026, 1)
    assert periods[-1] == (2026, 12)
    assert len(periods) == 12


def test_iter_periods_single_month():
    assert _iter_periods(date(2026, 6, 1), date(2026, 6, 30)) == [(2026, 6)]


def test_iter_periods_crosses_year_boundary():
    periods = _iter_periods(date(2025, 11, 1), date(2026, 2, 28))
    assert periods == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


# ── _superavit_y_estado ───────────────────────────────────────────────────────

def test_superavit_puro():
    # (gen 100 + bolsa 10) − (ppa 50 + consumo 20) = 40
    superavit, estado = _superavit_y_estado(100, 50, 20, 10)
    assert superavit == 40.0
    assert estado == "SUPERAVIT"


def test_deficit_puro():
    # (gen 10 + bolsa 0) − (ppa 50 + consumo 5) = -45
    superavit, estado = _superavit_y_estado(10, 50, 5, 0)
    assert superavit == -45.0
    assert estado == "DEFICIT"


def test_neutro_dentro_de_epsilon():
    superavit, estado = _superavit_y_estado(10.0000, 10.0000, 0, 0)
    assert estado == "NEUTRO"
    # Un descuadre por debajo del umbral tampoco marca déficit.
    _, estado2 = _superavit_y_estado(10.0, 10.0005, 0, 0)
    assert estado2 == "NEUTRO"


# ── _proyeccion_fin_anio ──────────────────────────────────────────────────────

def test_proyeccion_lineal():
    # 60 MWh acumulados en 6 meses → 10/mes → 120 a fin de año.
    assert _proyeccion_fin_anio(60, 6) == 120.0


def test_proyeccion_sin_datos_es_none():
    assert _proyeccion_fin_anio(0, 0) is None


# ── build_balance ─────────────────────────────────────────────────────────────

def test_build_balance_superavit_y_deficit():
    start, end = date(2026, 1, 1), date(2026, 2, 28)
    gen_map = {(2026, 1): 100.0, (2026, 2): 20.0}
    ppa_map = {(2026, 1): 50.0, (2026, 2): 50.0}
    consumo_map = {(2026, 1): 10.0, (2026, 2): 5.0}
    bolsa_map = {(2026, 1): 5.0}
    precio_map = {(2026, 1): 250.0}

    out = build_balance(start, end, gen_map, ppa_map, consumo_map, bolsa_map, precio_map)

    assert len(out["meses"]) == 2
    ene, feb = out["meses"]
    # Enero: (100 + 5) − (50 + 10) = 45 → superávit
    assert ene["superavit_mwh"] == 45.0 and ene["estado"] == "SUPERAVIT"
    assert ene["precio_bolsa_promedio"] == 250.0
    # Febrero: (20 + 0) − (50 + 5) = -35 → déficit; sin precio → None
    assert feb["superavit_mwh"] == -35.0 and feb["estado"] == "DEFICIT"
    assert feb["precio_bolsa_promedio"] is None

    resumen = out["resumen"]
    assert resumen["meses_con_datos"] == 2
    assert resumen["balance_acumulado_mwh"] == 10.0  # 45 + (-35)
    assert resumen["generacion_total_mwh"] == 120.0
    # Promedio mensual 5 MWh × 12 = 60
    assert resumen["proyeccion_fin_anio_mwh"] == 60.0


def test_build_balance_mes_sin_datos_queda_en_cero():
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    out = build_balance(start, end, {}, {}, {}, {}, {})
    assert len(out["meses"]) == 3
    for m in out["meses"]:
        assert m["generacion_real_mwh"] == 0.0
        assert m["superavit_mwh"] == 0.0
        assert m["estado"] == "NEUTRO"
        assert m["precio_bolsa_promedio"] is None
    # Sin generación → no hay meses YTD → proyección None.
    assert out["resumen"]["meses_con_datos"] == 0
    assert out["resumen"]["proyeccion_fin_anio_mwh"] is None


def test_build_balance_futuro_solo_ppa_no_arrastra_promedio():
    # Enero con generación real; febrero/marzo solo con compromiso PPA (futuro).
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    gen_map = {(2026, 1): 100.0}
    ppa_map = {(2026, 1): 40.0, (2026, 2): 40.0, (2026, 3): 40.0}
    out = build_balance(start, end, gen_map, ppa_map, {}, {}, {})

    # Meses futuros aparecen en la lista, en déficit por el compromiso.
    assert out["meses"][1]["estado"] == "DEFICIT"
    # Pero YTD y proyección solo cuentan enero (mes con generación).
    resumen = out["resumen"]
    assert resumen["meses_con_datos"] == 1
    assert resumen["balance_acumulado_mwh"] == 60.0  # 100 - 40
    assert resumen["proyeccion_fin_anio_mwh"] == 720.0  # 60 × 12


def test_build_balance_venta_bolsa_neta_puede_ser_negativa():
    # Solo actividad de mercado: compra neta (import > export) → bolsa negativa.
    start, end = date(2026, 5, 1), date(2026, 5, 31)
    out = build_balance(start, end, {}, {}, {}, {(2026, 5): -8.0}, {})
    mayo = out["meses"][0]
    assert mayo["venta_bolsa_mwh"] == -8.0
    assert mayo["superavit_mwh"] == -8.0 and mayo["estado"] == "DEFICIT"
