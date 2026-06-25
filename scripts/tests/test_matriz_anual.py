"""Tests standalone (sin pytest): `python scripts/tests/test_matriz_anual.py`."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datetime import date

# Stub mínimo de asignación GESCON para el helper (atributos que usa get_anual).
class _Proy:
    def __init__(self, nombre, sp, pid): self.nombre_comercial=nombre; self.sub_project=sp; self.id=pid
class _Asic:
    def __init__(self, nombre, sp, pid, pct, dup=False, fi=None, ff=None):
        self.proyecto=_Proy(nombre, sp, pid); self.proyecto_id=pid
        self.porcentaje_despacho=pct; self.es_duplicado=dup
        self.fecha_inicio=fi; self.fecha_fin=ff

def test_invariante_contrato_igual_suma_proyectos():
    from app.api.v1.cumplimiento import _anual_meses_para_contrato
    class C:  # contrato mínimo
        id=1; nombre_interno="X"; numero_codigo_contrato="C1"; comprador_nombre="Comp"
    today = date(2030, 1, 15)  # todos los meses del 2026 son pasados → tipo_datos "real"
    gpm = {m: [_Asic("A","spA",10,0.5), _Asic("B","spB",20,0.5)] for m in range(1,13)}
    # month_cache: gen bruta por (mes, sub_project)
    month_cache = {}
    for m in range(1,13):
        month_cache[(m,"spA")] = {"mwh": 100.0}
        month_cache[(m,"spB")] = {"mwh": 40.0}
    meses, proyectos = _anual_meses_para_contrato(C(), 2026, gpm, {}, month_cache, {}, today)
    assert len(meses) == 12 and len(proyectos) == 2
    for i, mes in enumerate(meses):
        suma = sum(p["meses"][i]["valor_mwh"] or 0 for p in proyectos)
        assert abs(mes["valor_mwh"] - suma) < 1e-6, f"mes {i+1}: {mes['valor_mwh']} != {suma}"

def test_rollup_cumplimiento():
    from app.api.v1.cumplimiento import _rollup_cumplimiento
    meses = [
        {"estado": "ok", "valor_mwh": 100, "min_mwh": 90, "compras_bolsa_mwh": 0, "exposicion_bolsa_duplicados_mwh": None},
        {"estado": "deficit", "valor_mwh": 80, "min_mwh": 90, "compras_bolsa_mwh": 10, "exposicion_bolsa_duplicados_mwh": None},
        {"estado": "excedente", "valor_mwh": 200, "min_mwh": 90, "compras_bolsa_mwh": 0, "exposicion_bolsa_duplicados_mwh": 5},
    ]
    r = _rollup_cumplimiento(meses)
    assert r["estado_cumplimiento"] == "no_cumple"
    assert r["meses_en_deficit"] == 1
    assert r["requiere_bolsa"] is True
    assert abs(r["total_anual_mwh"] - 380) < 1e-6
    assert abs(r["bolsa_anual_mwh"] - 15) < 1e-6  # 10 compras + 5 duplicados


def test_invariante_mes_actual():
    """Ejercita el path de mes actual (proyección) de _anual_meses_para_contrato.

    today = 2026-06-15 → mes 6 es mes actual (is_current=True).
    Meses 1..5 son pasados (real), mes 6 es proyectado, meses 7..12 son futuros.
    Invariante clave: contrato.meses[5].valor_mwh == Σ proyectos[*].meses[5].valor_mwh
    """
    from app.api.v1.cumplimiento import _anual_meses_para_contrato

    class C:
        id = 1; nombre_interno = "X"; numero_codigo_contrato = "C1"; comprador_nombre = "Comp"

    today = date(2026, 6, 15)  # mes 6 = mes actual
    year = 2026

    # 2 plantas con pct=0.5 c/u
    gpm = {m: [_Asic("A", "spA", 10, 0.5), _Asic("B", "spB", 20, 0.5)] for m in range(1, 13)}

    # month_cache: gen bruta por (mes, sub_project) — cubre meses pasados (1..5) y actual (6)
    month_cache = {}
    for m in range(1, 7):  # 1..6 inclusive (pasado + actual)
        month_cache[(m, "spA")] = {"mwh": 100.0}
        month_cache[(m, "spB")] = {"mwh": 40.0}

    # avg_cache: avg_daily (float escalar) por sub_project — usado en mes actual + futuros
    avg_cache = {
        "spA": 3.0,   # MWh/día promedio últimos 30d
        "spB": 1.5,
    }

    meses, proyectos = _anual_meses_para_contrato(C(), year, gpm, {}, month_cache, avg_cache, today)

    assert len(meses) == 12
    assert len(proyectos) == 2

    # Invariante para mes actual (índice 5 = mes 6)
    mes_actual = meses[5]
    assert mes_actual["tipo_datos"] == "mes_actual", f"esperaba mes_actual, got {mes_actual['tipo_datos']}"
    suma_proy_actual = sum(p["meses"][5]["valor_mwh"] or 0 for p in proyectos)
    assert abs(mes_actual["valor_mwh"] - suma_proy_actual) < 1e-6, (
        f"mes 6 contrato={mes_actual['valor_mwh']} != suma proyectos={suma_proy_actual}"
    )

    # Invariante para mes pasado (índice 0 = mes 1) — tipo "real"
    mes_pasado = meses[0]
    assert mes_pasado["tipo_datos"] == "real", f"esperaba real, got {mes_pasado['tipo_datos']}"
    suma_proy_pasado = sum(p["meses"][0]["valor_mwh"] or 0 for p in proyectos)
    assert abs(mes_pasado["valor_mwh"] - suma_proy_pasado) < 1e-6, (
        f"mes 1 contrato={mes_pasado['valor_mwh']} != suma proyectos={suma_proy_pasado}"
    )


def test_dedup_fetch_set():
    """Verifica que _build_fetch_sets deduplica fetches cuando 2 contratos comparten sub_project."""
    from app.api.v1.cumplimiento import _build_fetch_sets
    from datetime import date
    today = date(2026, 6, 15)
    # Dos contratos comparten "spA" en meses pasados → debe deduplicar.
    # need_month usa orden (m, sp) igual que get_anual / month_cache[(m, sp)].
    gpm_por_contrato = {
        1: {m: [_Asic("A", "spA", 10, 1.0)] for m in range(1, 13)},
        2: {m: [_Asic("A", "spA", 10, 1.0), _Asic("B", "spB", 20, 1.0)] for m in range(1, 13)},
    }
    need_month, need_avg = _build_fetch_sets(gpm_por_contrato, 2026, today)
    # spA en meses pasados (1..5) una sola vez aunque esté en 2 contratos
    assert (1, "spA") in need_month, f"(1, 'spA') no encontrado en need_month={need_month}"
    assert len([x for x in need_month if x == (1, "spA")]) == 1, "deduplicación fallida"
    assert "spA" in need_avg, f"'spA' no encontrado en need_avg={need_avg}"
    # spB también debe estar en need_month para meses pasados
    assert (1, "spB") in need_month, f"(1, 'spB') no encontrado en need_month={need_month}"
    # Mes actual (6) debe estar en need_month Y need_avg
    assert (6, "spA") in need_month, f"(6, 'spA') no en need_month (mes actual)"
    assert (6, "spB") in need_month, f"(6, 'spB') no en need_month (mes actual)"
    # Meses futuros (7..12) NO en need_month, solo en need_avg
    assert (7, "spA") not in need_month, f"(7, 'spA') no debería estar en need_month"
    assert "spB" in need_avg, f"'spB' no en need_avg"


if __name__ == "__main__":
    test_invariante_contrato_igual_suma_proyectos()
    print("OK test_matriz_anual (Task 1)")
    test_rollup_cumplimiento()
    print("OK test_rollup_cumplimiento (Task 2)")
    test_invariante_mes_actual()
    print("OK test_invariante_mes_actual (Task 2)")
    test_dedup_fetch_set()
    print("OK test_dedup_fetch_set (Task 3)")
