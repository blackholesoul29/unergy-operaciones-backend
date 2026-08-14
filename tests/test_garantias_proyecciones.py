"""Motor de garantía: fórmula pura, extracción de neto y orquestación con deps inyectadas.
Sin BD, sin red, sin reloj."""
from datetime import date

from app.services.garantias_proyecciones import calcular_garantia, neto_de_balance, proyecciones


def test_formula_base_valoriza_neto_en_kwh_mas_regulatorio():
    # neto 10 MWh = 10_000 kWh; precio 900 COP/kWh -> 9_000_000; + reg 1_000_000 = 10_000_000
    r = calcular_garantia(neto_mwh=10.0, precio_cop_kwh=900.0, costo_regulatorio=1_000_000.0)
    assert r["valor_energia"] == 9_000_000.0
    assert r["garantia_total"] == 10_000_000.0
    assert r["energia_neta_kwh"] == 10_000.0


def test_planta_nueva_suma_termino_editable():
    # 2 plantas nuevas × 180 kWh × 900 = 324_000, aditivo
    r = calcular_garantia(neto_mwh=0.0, precio_cop_kwh=900.0, costo_regulatorio=0.0,
                          plantas_nuevas=2, kwh_planta_nueva=180.0)
    assert r["valor_plantas_nuevas"] == 324_000.0
    assert r["garantia_total"] == 324_000.0


def test_neto_negativo_permitido():
    # si compras > ventas el neto es negativo; la fórmula lo respeta (se valida vs XM luego)
    r = calcular_garantia(neto_mwh=-5.0, precio_cop_kwh=1000.0, costo_regulatorio=0.0)
    assert r["valor_energia"] == -5_000_000.0


def _balance(venta, compra_directa):
    def celda(t): return {"real": 0.0, "proyectado": t["p"], "total": t["t"], "n_plantas": 1}
    return {
        "ungg": {
            "venta_bolsa": celda(venta),
            "compra_bolsa_directa": celda(compra_directa),
            "compra_bolsa_no_directa": celda({"p": 99.0, "t": 99.0}),  # NO debe influir
            "compra_bolsa_total": celda({"p": 99.0, "t": 99.0}),        # NO debe influir
            "neto": celda({"p": -1.0, "t": -1.0}),                       # NO debe influir
        },
        "ungc": {"venta_bolsa": celda({"p": 7.0, "t": 7.0})},            # NO debe influir
    }


def test_neto_proyectado_es_venta_menos_compra_directa():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})
    assert neto_de_balance(bal, "proyectado") == 26.0   # 30 - 4


def test_neto_total_usa_campo_total():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})
    assert neto_de_balance(bal, "total") == 44.0        # 50 - 6


def test_proyecciones_arma_dos_ventanas_con_deps_inyectadas():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})

    def calcular_balance_fn(anio, mes):
        assert (anio, mes) == (2026, 8)   # siempre el mes actual
        return {"balance": bal, "periodo": {"fecha_corte": "2026-08-14"}}

    def precio_fn():
        return 900.0

    regs = {(2026, 7): 1_000_000.0, (2026, 8): 2_000_000.0}
    def regulatorio_fn(anio, mes):
        return {"valor": regs[(anio, mes)], "anio": anio, "mes": mes, "fallback": False}

    out = proyecciones(date(2026, 8, 14), calcular_balance_fn=calcular_balance_fn,
                       precio_fn=precio_fn, regulatorio_fn=regulatorio_fn)

    assert out["precio_bolsa_cop_kwh"] == 900.0
    v1, v2 = out["ventanas"]
    # Ventana 1: resto mes actual (proyectado 26 MWh) × 900 × 1000 + reg julio 1_000_000
    assert v1["clave"] == "resto_mes_actual"
    assert (v1["anio"], v1["mes"]) == (2026, 8)
    assert v1["garantia_total"] == 26.0 * 1000 * 900.0 + 1_000_000.0
    # Ventana 2: mes siguiente (total 44 MWh) × 900 × 1000 + reg agosto 2_000_000
    assert v2["clave"] == "mes_siguiente"
    assert (v2["anio"], v2["mes"]) == (2026, 9)
    assert v2["garantia_total"] == 44.0 * 1000 * 900.0 + 2_000_000.0


def test_proyecciones_maneja_rollover_de_diciembre():
    bal = _balance(venta={"p": 1.0, "t": 1.0}, compra_directa={"p": 0.0, "t": 0.0})
    calls = {}
    def regulatorio_fn(anio, mes):
        calls[(anio, mes)] = True
        return {"valor": 0.0, "anio": anio, "mes": mes, "fallback": False}
    out = proyecciones(date(2026, 12, 10),
                       calcular_balance_fn=lambda a, m: {"balance": bal, "periodo": {}},
                       precio_fn=lambda: 100.0, regulatorio_fn=regulatorio_fn)
    v1, v2 = out["ventanas"]
    assert (v1["anio"], v1["mes"]) == (2026, 12)
    assert (v2["anio"], v2["mes"]) == (2027, 1)          # rollover de año
    assert (2026, 11) in calls and (2026, 12) in calls   # regulatorio del mes anterior a cada ventana
