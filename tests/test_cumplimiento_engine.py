"""Motor de cierre mensual de cumplimiento PPA.

Pruebas puras (sin BD): selección de periodo y coherencia de las columnas SQL
que consulta el auto-populate de XM contra el DDL real de `precios_bolsa_diario`.
"""
import os
import re
from datetime import date

from app.services.cumplimiento_engine import periodo_anterior

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── periodo_anterior ──────────────────────────────────────────────────────────

def test_periodo_anterior_mes_normal():
    assert periodo_anterior(date(2026, 7, 13)) == (2026, 6)


def test_periodo_anterior_cruza_anio():
    """El día 1 de enero el job debe cerrar diciembre del año anterior."""
    assert periodo_anterior(date(2026, 1, 1)) == (2025, 12)


def test_periodo_anterior_desde_marzo_da_febrero():
    assert periodo_anterior(date(2026, 3, 1)) == (2026, 2)


def test_periodo_anterior_es_el_mes_previo_para_todo_el_anio():
    for mes in range(1, 13):
        anio_prev, mes_prev = periodo_anterior(date(2026, mes, 1))
        if mes == 1:
            assert (anio_prev, mes_prev) == (2025, 12)
        else:
            assert (anio_prev, mes_prev) == (2026, mes - 1)


# ── regresión: columnas reales de precios_bolsa_diario ────────────────────────

def _columnas_precios_bolsa_diario() -> set[str]:
    """Extrae las columnas del CREATE TABLE de precios_bolsa_diario en main.py."""
    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as fh:
        main_src = fh.read()
    bloque = re.search(
        r"CREATE TABLE IF NOT EXISTS precios_bolsa_diario \((.*?)\)\"\"\"",
        main_src,
        re.S,
    )
    assert bloque, "No se encontró el DDL de precios_bolsa_diario en app/main.py"
    cols = set()
    for linea in bloque.group(1).splitlines():
        m = re.match(r"\s*([a-z_]+)\s+[A-Z]", linea)
        if m:
            cols.add(m.group(1))
    return cols


def test_auto_populate_solo_usa_columnas_existentes_de_precios_bolsa():
    """El fallback a precio de bolsa consultaba `precio_promedio_kwh`, que no
    existe: la columna real es `precio_promedio`. Eso reventaba con UndefinedColumn
    en toda liquidación sin tarifa PPA."""
    cols = _columnas_precios_bolsa_diario()
    assert "precio_promedio" in cols
    assert "precio_promedio_kwh" not in cols

    with open(os.path.join(ROOT, "app", "api", "v1", "liquidaciones.py"), encoding="utf-8") as fh:
        liq_src = fh.read()

    consulta = re.search(
        r"SELECT AVG\((\w+)\) as tarifa_avg\s+FROM precios_bolsa_diario(.*?)\"\"\"",
        liq_src,
        re.S,
    )
    assert consulta, "No se encontró la consulta de precio de bolsa en auto_populate_xm_datos"
    assert consulta.group(1) in cols, (
        f"auto_populate promedia `{consulta.group(1)}`, que no existe en precios_bolsa_diario"
    )
    for ref in re.findall(r"([a-z_]*precio[a-z_]*)", consulta.group(2)):
        assert ref in cols, f"auto_populate referencia `{ref}`, inexistente en precios_bolsa_diario"


# ── regresión: el engine solo toca columnas que el DDL crea ───────────────────

def test_engine_solo_usa_columnas_existentes_de_cumplimiento_cierre_log():
    """Mismo fallo que arriba, pero para la tabla nueva: el INSERT/SELECT del
    engine debe cuadrar con el CREATE TABLE de _PENDING_DDLS."""
    import inspect

    from app.services import cumplimiento_engine

    with open(os.path.join(ROOT, "app", "main.py"), encoding="utf-8") as fh:
        main_src = fh.read()
    bloque = re.search(
        r"CREATE TABLE IF NOT EXISTS cumplimiento_cierre_log \((.*?)\)\"\"\"",
        main_src,
        re.S,
    )
    assert bloque, "No se encontró el DDL de cumplimiento_cierre_log en app/main.py"
    cols = {
        m.group(1)
        for m in (re.match(r"\s*([a-z_]+)\s+[A-Z]", l) for l in bloque.group(1).splitlines())
        if m
    }
    assert {"anio", "mes", "origen", "error", "ejecutado_at"} <= cols

    src = inspect.getsource(cumplimiento_engine)

    insert = re.search(r"INSERT INTO cumplimiento_cierre_log\s*\((.*?)\)", src, re.S)
    assert insert, "No se encontró el INSERT del engine"
    for col in re.findall(r"[a-z_]+", insert.group(1)):
        assert col in cols, f"El INSERT escribe `{col}`, inexistente en cumplimiento_cierre_log"

    select = re.search(r"SELECT (.*?)\s+FROM cumplimiento_cierre_log", src, re.S)
    assert select, "No se encontró el SELECT del engine"
    for col in re.findall(r"[a-z_]+", select.group(1)):
        assert col in cols, f"El SELECT lee `{col}`, inexistente en cumplimiento_cierre_log"
