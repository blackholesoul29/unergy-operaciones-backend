"""La matriz anual prorrateaba por REGLA DE TRES (generacion_mes_completo x
dias_vigentes/dias_mes) en vez de sumar la generacion REAL de los dias en que
el registro estuvo vigente. Con generacion diaria no pareja (clima, etc.) el
resultado no coincidia con la vista "Generacion solar" filtrada por el mismo
rango de fechas.

Caso real: Baraya en Terpel 2 (SIC 89115), vigente 7-25 feb 2026 (19/28 dias).
La matriz calculaba 158.083 (total de febrero) x 19/28 = 107.271. La vista
Generacion solar (mismo rango, 7 al 25) daba 129.090 -- porque esos 19 dias en
particular generaron mas que el promedio del mes. El fix suma directamente la
generacion real de esos 19 dias (misma fuente y metodo que Generacion solar:
_fetch_range / _sumar_deltas_en_rango), no reparte el total mensual.
"""
from datetime import date, datetime
from types import SimpleNamespace

from app.api.v1.cumplimiento import (
    _anual_meses_para_contrato,
    _build_fetch_sets,
    _sumar_deltas_en_rango,
)


def _asic(proyecto_id, nombre, sub_project, pct, fecha_inicio=None, fecha_fin=None, es_duplicado=False):
    return SimpleNamespace(
        proyecto_id=proyecto_id,
        proyecto=SimpleNamespace(nombre_comercial=nombre, sub_project=sub_project),
        porcentaje_despacho=pct,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        es_duplicado=es_duplicado,
    )


def _contrato(fecha_inicio=None, fecha_fin=None):
    return SimpleNamespace(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)


TODAY = date(2026, 7, 1)  # "hoy" muy posterior a febrero-2026: todo el año es histórico


# ── _sumar_deltas_en_rango (función pura) ──────────────────────────────────────

def test_sumar_deltas_usa_lectura_anterior_como_base_del_primer_punto():
    records = [
        {"time_stamp": "2026-02-06T23:00:00Z", "generacion": 500},  # "antes" del rango
        {"time_stamp": "2026-02-07T00:00:00Z", "generacion": 0},    # reinicio
        {"time_stamp": "2026-02-07T06:00:00Z", "generacion": 100},
        {"time_stamp": "2026-02-07T12:00:00Z", "generacion": 500},
        {"time_stamp": "2026-02-07T18:00:00Z", "generacion": 600},
        {"time_stamp": "2026-02-08T00:00:00Z", "generacion": 0},    # reinicio
        {"time_stamp": "2026-02-08T12:00:00Z", "generacion": 300},
        {"time_stamp": "2026-02-09T00:00:00Z", "generacion": 0},    # fuera del rango
    ]
    d_from = datetime(2026, 2, 7, 0, 0, 0)
    d_to = datetime(2026, 2, 8, 23, 59, 59)
    mwh = _sumar_deltas_en_rango(records, d_from, d_to)
    # deltas dentro del rango: 100 + 400 + 100 + 0(reinicio) + 300 = 900 kWh
    assert mwh == 0.9


def test_sumar_deltas_sin_lecturas_en_el_rango_da_none():
    records = [{"time_stamp": "2026-01-01T00:00:00Z", "generacion": 10}]
    mwh = _sumar_deltas_en_rango(records, datetime(2026, 2, 1), datetime(2026, 2, 28, 23, 59, 59))
    assert mwh is None


def test_sumar_deltas_ignora_lecturas_sin_generacion():
    records = [
        {"time_stamp": "2026-02-06T23:00:00Z", "generacion": 0},
        {"time_stamp": "2026-02-07T06:00:00Z", "generacion": None},  # dato faltante, se ignora
        {"time_stamp": "2026-02-07T12:00:00Z", "generacion": 50},
    ]
    mwh = _sumar_deltas_en_rango(records, datetime(2026, 2, 7, 0, 0, 0), datetime(2026, 2, 7, 23, 59, 59))
    assert mwh == 0.05


# ── _build_fetch_sets: decide cuándo pedir mes completo vs rango ──────────────

def test_build_fetch_sets_vigencia_mes_completo_va_a_need_month():
    asic = _asic(4, "Baraya", "baraya", 1.0, fecha_inicio=None, fecha_fin=None)
    gpm = {m: ([asic] if m == 2 else []) for m in range(1, 13)}
    need_month, need_avg, need_range = _build_fetch_sets({1: gpm}, 2026, TODAY)
    assert (2, "baraya") in need_month
    assert not need_range


def test_build_fetch_sets_vigencia_parcial_va_a_need_range():
    asic = _asic(4, "Baraya", "baraya", 1.0, fecha_inicio=date(2026, 2, 7), fecha_fin=date(2039, 12, 31))
    gpm = {m: ([asic] if m == 2 else []) for m in range(1, 13)}
    need_month, need_avg, need_range = _build_fetch_sets({1: gpm}, 2026, TODAY)
    assert (2, "baraya") not in need_month
    assert ("baraya", date(2026, 2, 7), date(2026, 2, 28)) in need_range


# ── _anual_meses_para_contrato: usa el rango real, no prorratea ───────────────

def test_vigencia_parcial_usa_generacion_real_del_rango_no_prorrateo():
    """Caso Baraya: 7-25 feb (19/28 días). Generación total de febrero = 158.083
    (si se prorrateara: 158.083*19/28=107.27), pero la real de esos 19 días
    específicos es 129.090 (Generación solar). El contrato debe reflejar
    129.090, no 107.27."""
    # fecha_fin=25-feb simula la fecha_fin EFECTIVA ya recortada por
    # _resolve_gescon (relevo con Yurbaqua desde el 26) — no la fecha_fin real
    # del registro (2039), que es justamente lo que causaba el bug original.
    baraya = _asic(4, "Baraya", "baraya", 1.0,
                    fecha_inicio=date(2026, 2, 7), fecha_fin=date(2026, 2, 25))
    gpm = {m: ([baraya] if m == 2 else []) for m in range(1, 13)}
    month_cache = {(2, "baraya"): {"mwh": 158.083, "n_records": 100, "ultimo_dia": 28}}
    range_cache = {("baraya", date(2026, 2, 7), date(2026, 2, 25)): {"mwh": 129.090, "n_records": 50}}

    meses, _proyectos = _anual_meses_para_contrato(
        _contrato(), 2026, gpm, {}, month_cache, {}, TODAY, range_cache,
    )
    feb = meses[1]
    plantas = feb["plantas"]
    assert len(plantas) == 1
    p = plantas[0]
    assert p["dias_en_contrato"] == 19
    assert p["dias_mes"] == 28
    assert p["gen_planta_mwh"] == 129.090
    assert p["gen_contrato_mwh"] == 129.090          # pct=100% → igual a gen_planta_mwh
    assert feb["gen_mwh"] == 129.090
    # NO debe dar el valor prorrateado por regla de tres
    prorrateado_regla_de_tres = round(158.083 * 19 / 28, 3)
    assert p["gen_contrato_mwh"] != prorrateado_regla_de_tres


def test_vigencia_parcial_aplica_pct_despacho_sobre_la_generacion_real():
    verso = _asic(53, "Verso", "verso", 0.5,
                   fecha_inicio=date(2026, 2, 12), fecha_fin=date(2026, 7, 31))
    gpm = {m: ([verso] if m == 2 else []) for m in range(1, 13)}
    range_cache = {("verso", date(2026, 2, 12), date(2026, 2, 28)): {"mwh": 200.0, "n_records": 40}}

    meses, _ = _anual_meses_para_contrato(_contrato(), 2026, gpm, {}, {}, {}, TODAY, range_cache)
    p = meses[1]["plantas"][0]
    assert p["gen_planta_mwh"] == 200.0
    assert p["gen_contrato_mwh"] == 100.0   # 200 * 0.5


def test_vigencia_mes_completo_sin_cambios_usa_month_cache():
    """Control: un registro vigente todo el mes debe seguir dando exactamente
    el total mensual (no se toca este caso, no se pide range_cache)."""
    planta = _asic(9, "Planta Estable", "estable", 1.0, fecha_inicio=None, fecha_fin=None)
    gpm = {m: ([planta] if m == 2 else []) for m in range(1, 13)}
    month_cache = {(2, "estable"): {"mwh": 200.0, "n_records": 100, "ultimo_dia": 28}}

    meses, _ = _anual_meses_para_contrato(_contrato(), 2026, gpm, {}, month_cache, {}, TODAY, {})
    p = meses[1]["plantas"][0]
    assert p["dias_en_contrato"] == 28
    assert p["gen_planta_mwh"] == 200.0
    assert p["gen_contrato_mwh"] == 200.0


def test_rango_no_disponible_en_cache_no_rompe_da_none():
    baraya = _asic(4, "Baraya", "baraya", 1.0,
                    fecha_inicio=date(2026, 2, 7), fecha_fin=date(2039, 12, 31))
    gpm = {m: ([baraya] if m == 2 else []) for m in range(1, 13)}
    meses, _ = _anual_meses_para_contrato(_contrato(), 2026, gpm, {}, {}, {}, TODAY, {})
    p = meses[1]["plantas"][0]
    assert p["gen_planta_mwh"] is None
    assert p["gen_contrato_mwh"] is None
