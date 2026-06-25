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

if __name__ == "__main__":
    test_invariante_contrato_igual_suma_proyectos()
    print("OK test_matriz_anual (Task 1)")
