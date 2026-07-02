"""Estrategia (/simulador), Matriz (/anual-matriz) y Energía transada
(/energia-transada) DEBEN dar la misma energía para la misma planta/mes.

Antes divergían en vigencia PARCIAL de un mes (relevo/arranque/terminación
intra-mes):
  - Matriz: ya sumaba la generación REAL de los días vigentes (fix af0e070).
  - Estrategia (/simulador): devolvía el total del MES completo (month_mwh) sin
    escalar por la vigencia → el front mostraba month_mwh × pct = total del mes.
  - Energía transada: prorrateaba el total del mes por fracción de días
    (regla de tres: total × dias/dias_mes).

Ahora las tres pasan por el mismo helper `_gen_vigencia_mwh`: vigencia completa
→ total del mes; vigencia parcial → suma real de esos días (NUNCA regla de tres).

Caso real: Baraya en Terpel 2, 7-25 feb 2026 (19/28 días). Total de febrero =
158.083; regla de tres daría 158.083×19/28 = 107.271; la generación real de esos
19 días (Generación solar) es 129.090. Las tres vistas deben dar 129.090.
"""
from datetime import date
from types import SimpleNamespace

from app.api.v1.cumplimiento import (
    _anual_meses_para_contrato,
    _gen_vigencia_mwh,
    _vigencia_window,
)

TODAY = date(2026, 7, 1)  # febrero-2026 es histórico


def _asic(proyecto_id, nombre, sub_project, pct, fecha_inicio=None, fecha_fin=None, es_duplicado=False):
    return SimpleNamespace(
        proyecto_id=proyecto_id,
        proyecto=SimpleNamespace(nombre_comercial=nombre, sub_project=sub_project),
        porcentaje_despacho=pct,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        es_duplicado=es_duplicado,
    )


# ── Helper compartido: vigencia parcial usa el rango real, no regla de tres ───

def test_gen_vigencia_parcial_usa_rango_no_regla_de_tres():
    eff_start, eff_end = date(2026, 2, 7), date(2026, 2, 25)
    total_dias = 28
    month_gen, range_gen = 158.083, 129.090
    val = _gen_vigencia_mwh(eff_start, eff_end, total_dias, month_gen, range_gen)
    assert val == 129.090
    # NO es el prorrateo por regla de tres del total mensual
    assert val != round(month_gen * 19 / 28, 3)


def test_gen_vigencia_mes_completo_da_total_del_mes():
    eff_start, eff_end = date(2026, 2, 1), date(2026, 2, 28)
    val = _gen_vigencia_mwh(eff_start, eff_end, 28, 158.083, None)
    assert val == 158.083


def test_gen_vigencia_sin_dias_activos_da_none():
    # eff_end anterior a eff_start (registro no vigente en el período)
    val = _gen_vigencia_mwh(date(2026, 2, 20), date(2026, 2, 10), 28, 158.083, 129.090)
    assert val is None


# ── Estrategia y Matriz coinciden en vigencia parcial ─────────────────────────

def _estrategia_gen(sub_project, fecha_inicio, fecha_fin, first_day, last_day,
                    total_dias, month_cache, range_cache, pct):
    """Reproduce exactamente el cálculo de energía de get_simulador (_scoped_gen,
    rama mes pasado) para una asignación: energía real de la vigencia × pct."""
    eff_start, eff_end = _vigencia_window(fecha_inicio, fecha_fin, first_day, last_day)
    month_gen = month_cache.get((2, sub_project), {}).get("mwh")
    range_gen = range_cache.get((sub_project, eff_start, eff_end), {}).get("mwh")
    gv = _gen_vigencia_mwh(eff_start, eff_end, total_dias, month_gen, range_gen)
    return round(gv * pct, 3) if gv is not None else None


def test_estrategia_y_matriz_coinciden_vigencia_parcial():
    """Baraya en Terpel 2, 7-25 feb: ambas vistas deben dar 129.090 (no 107.271)."""
    sub_project, pct = "baraya", 1.0
    fi, ff = date(2026, 2, 7), date(2026, 2, 25)
    first_day, last_day, total_dias = date(2026, 2, 1), date(2026, 2, 28), 28
    month_cache = {(2, sub_project): {"mwh": 158.083}}
    range_cache = {(sub_project, fi, ff): {"mwh": 129.090}}

    # Matriz
    baraya = _asic(4, "Baraya", sub_project, pct, fecha_inicio=fi, fecha_fin=ff)
    gpm = {m: ([baraya] if m == 2 else []) for m in range(1, 13)}
    meses, _ = _anual_meses_para_contrato(
        SimpleNamespace(fecha_inicio=None, fecha_fin=None),
        2026, gpm, {}, month_cache, {}, TODAY, range_cache,
    )
    matriz_val = meses[1]["plantas"][0]["gen_contrato_mwh"]

    # Estrategia
    estrategia_val = _estrategia_gen(
        sub_project, fi, ff, first_day, last_day, total_dias, month_cache, range_cache, pct,
    )

    assert matriz_val == 129.090
    assert estrategia_val == 129.090
    assert estrategia_val == matriz_val
    # y ninguna es el prorrateo por regla de tres
    assert matriz_val != round(158.083 * 19 / 28, 3)


def test_estrategia_y_matriz_coinciden_mes_completo():
    """Control: vigencia todo el mes → ambas dan el total mensual, iguales."""
    sub_project, pct = "estable", 1.0
    first_day, last_day, total_dias = date(2026, 2, 1), date(2026, 2, 28), 28
    month_cache = {(2, sub_project): {"mwh": 200.0}}

    planta = _asic(9, "Estable", sub_project, pct, fecha_inicio=None, fecha_fin=None)
    gpm = {m: ([planta] if m == 2 else []) for m in range(1, 13)}
    meses, _ = _anual_meses_para_contrato(
        SimpleNamespace(fecha_inicio=None, fecha_fin=None),
        2026, gpm, {}, month_cache, {}, TODAY, {},
    )
    matriz_val = meses[1]["plantas"][0]["gen_contrato_mwh"]
    estrategia_val = _estrategia_gen(
        sub_project, None, None, first_day, last_day, total_dias, month_cache, {}, pct,
    )
    assert matriz_val == 200.0
    assert estrategia_val == 200.0
    assert estrategia_val == matriz_val
