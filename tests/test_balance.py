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
    assert _proyeccion_fin_anio(60, 6, proyectar=True) == 120.0


def test_proyeccion_sin_datos_es_none():
    assert _proyeccion_fin_anio(0, 0, proyectar=True) is None


def test_proyeccion_no_proyectar_es_none():
    # Con datos pero fuera de un año calendario → no se proyecta.
    assert _proyeccion_fin_anio(60, 6, proyectar=False) is None


# ── build_balance ─────────────────────────────────────────────────────────────

def test_build_balance_superavit_y_deficit():
    # Año calendario completo con datos solo en ene/feb (resto sin dato).
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    gen_map = {(2026, 1): 100.0, (2026, 2): 20.0}
    ppa_map = {(2026, 1): 50.0, (2026, 2): 50.0}
    consumo_map = {(2026, 1): 10.0, (2026, 2): 5.0}
    bolsa_map = {(2026, 1): 5.0}
    precio_map = {(2026, 1): 250.0}

    out = build_balance(start, end, gen_map, ppa_map, consumo_map, bolsa_map, precio_map)

    assert len(out["meses"]) == 12
    ene, feb = out["meses"][0], out["meses"][1]
    # Enero: (100 + 5) − (50 + 10) = 45 → superávit
    assert ene["realizado"] is True
    assert ene["superavit_mwh"] == 45.0 and ene["estado"] == "SUPERAVIT"
    assert ene["precio_bolsa_promedio_cop_kwh"] == 250.0
    # Febrero: (20 + 0) − (50 + 5) = -35 → déficit; sin precio → None
    assert feb["realizado"] is True
    assert feb["superavit_mwh"] == -35.0 and feb["estado"] == "DEFICIT"
    assert feb["precio_bolsa_promedio_cop_kwh"] is None
    # Marzo en adelante: sin dato real → SIN_DATOS (aunque haya iterado el mes).
    assert out["meses"][2]["realizado"] is False
    assert out["meses"][2]["estado"] == "SIN_DATOS"

    resumen = out["resumen"]
    assert resumen["meses_con_datos"] == 2
    assert resumen["balance_acumulado_mwh"] == 10.0  # 45 + (-35)
    assert resumen["generacion_total_mwh"] == 120.0
    # Año calendario → sí proyecta: promedio mensual 5 MWh × 12 = 60
    assert resumen["proyeccion_fin_anio_mwh"] == 60.0


def test_build_balance_mes_sin_datos_es_sin_datos():
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    out = build_balance(start, end, {}, {}, {}, {}, {})
    assert len(out["meses"]) == 3
    for m in out["meses"]:
        assert m["realizado"] is False
        assert m["generacion_real_mwh"] == 0.0
        assert m["superavit_mwh"] == 0.0
        # Un mes sin dato real NO es "neutro" (que implicaría cuadre): es SIN_DATOS.
        assert m["estado"] == "SIN_DATOS"
        assert m["precio_bolsa_promedio_cop_kwh"] is None
    # Sin dato real → no hay meses YTD → proyección None.
    assert out["resumen"]["meses_con_datos"] == 0
    assert out["resumen"]["proyeccion_fin_anio_mwh"] is None


def test_build_balance_futuro_solo_ppa_no_es_deficit_ni_arrastra_promedio():
    # Enero con generación real; febrero/marzo solo con compromiso PPA (futuro).
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    gen_map = {(2026, 1): 100.0}
    ppa_map = {(2026, 1): 40.0, (2026, 2): 40.0, (2026, 3): 40.0}
    out = build_balance(start, end, gen_map, ppa_map, {}, {}, {})

    # Un mes futuro con solo compromiso PPA NO se pinta como déficit real.
    assert out["meses"][1]["realizado"] is False
    assert out["meses"][1]["estado"] == "SIN_DATOS"
    # YTD solo cuenta enero (mes con dato real).
    resumen = out["resumen"]
    assert resumen["meses_con_datos"] == 1
    assert resumen["balance_acumulado_mwh"] == 60.0  # 100 - 40
    # Rango ene-mar (no año calendario) → no proyecta a fin de año.
    assert resumen["proyeccion_fin_anio_mwh"] is None


def test_build_balance_mes_pasado_con_consumo_sin_generacion_es_realizado():
    # Un mes con consumo real pero sin generación registrada SÍ está realizado
    # (no debe tratarse como futuro por faltar generación).
    start, end = date(2026, 4, 1), date(2026, 4, 30)
    out = build_balance(start, end, {}, {}, {(2026, 4): 12.0}, {}, {})
    abril = out["meses"][0]
    assert abril["realizado"] is True
    assert abril["consumo_clientes_mwh"] == 12.0
    # (0 gen + 0 bolsa) − (0 ppa + 12 consumo) = -12 → déficit real.
    assert abril["superavit_mwh"] == -12.0 and abril["estado"] == "DEFICIT"
    assert out["resumen"]["meses_con_datos"] == 1


def test_proyeccion_solo_para_anio_calendario():
    gen_map = {(2026, 1): 100.0}
    # Rango custom (no 1-ene→31-dic) → sin proyección aunque haya datos.
    out_custom = build_balance(date(2026, 1, 1), date(2026, 6, 30), gen_map, {}, {}, {}, {})
    assert out_custom["resumen"]["proyeccion_fin_anio_mwh"] is None
    # Año calendario → sí proyecta.
    out_anio = build_balance(date(2026, 1, 1), date(2026, 12, 31), gen_map, {}, {}, {}, {})
    assert out_anio["resumen"]["proyeccion_fin_anio_mwh"] == 1200.0  # 100/1 × 12


def test_build_balance_venta_bolsa_neta_puede_ser_negativa():
    # Solo actividad de mercado: compra neta (import > export) → bolsa negativa.
    start, end = date(2026, 5, 1), date(2026, 5, 31)
    out = build_balance(start, end, {}, {}, {}, {(2026, 5): -8.0}, {})
    mayo = out["meses"][0]
    assert mayo["realizado"] is True
    assert mayo["venta_bolsa_mwh"] == -8.0
    assert mayo["superavit_mwh"] == -8.0 and mayo["estado"] == "DEFICIT"
