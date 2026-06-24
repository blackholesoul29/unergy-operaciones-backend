"""
Tests de la re-división del Panel Contable (panel_contable.redividir):

Reconstruir la base al 100% desde líneas YA divididas y volver a repartir con los
% correctos, sin re-subir el ER. Cubre el bug de escala (% guardado en fracción →
valores 100× menores) y la idempotencia en paneles sanos.
"""
from app.api.v1.panel_contable import (
    _reconstruir_base, _redividir_lineas, _division_desactualizada,
)


def _inv(id, nombre, pct):
    return {"id": id, "nombre": nombre, "pct": pct, "fraccion": pct / 100.0}


def _linea(grupo, concepto, pid, pct, valor, orden):
    return {
        "proyecto_inversionista_id": pid, "porcentaje": pct, "valor_cop": valor,
        "grupo": grupo, "concepto": concepto, "hoja": None, "celda": None,
        "comprobante_contable": None, "orden": orden,
    }


# ── Caso bug: un inversionista guardado como "1%" (fracción 1.0 mal escalada) ──────

def test_redivide_un_inversionista_mal_escalado():
    # Snapshot roto: pct=1.0 (mostrado "1%"), valor = base * 0.01 (130.685.192 / 100).
    lineas = [_linea("ingresos", "Ingreso Bruto", 39, 1.0, 1_306_851.92, 0)]
    invs = [_inv(39, "GD EL REMOLINO 1", 100.0)]  # % correcto desde proyecto_inversionistas

    assert _division_desactualizada(lineas, invs) is True
    nuevas = _redividir_lineas(lineas, invs)
    assert len(nuevas) == 1
    ln = nuevas[0]
    assert ln["porcentaje"] == 100.0
    # base reconstruida = 1.306.851,92 / 0,01 = 130.685.192
    assert abs(ln["valor_cop"] - 130_685_192.0) < 1.0


# ── Caso bug multi-inversionista (Baraya: 26/12/62 guardado como 0.26/0.12/0.62) ──

def test_redivide_multi_inversionista_mal_escalado():
    base = 73_251_930.0
    lineas = [
        _linea("ingresos", "Ingreso Bruto", 15, 0.26, round(base * 0.0026, 2), 0),
        _linea("ingresos", "Ingreso Bruto", 16, 0.12, round(base * 0.0012, 2), 1),
        _linea("ingresos", "Ingreso Bruto", 17, 0.62, round(base * 0.0062, 2), 2),
    ]
    invs = [_inv(15, "SOMOS", 26.0), _inv(16, "Solenium", 12.0), _inv(17, "SUNO", 62.0)]

    assert _division_desactualizada(lineas, invs) is True
    nuevas = _redividir_lineas(lineas, invs)
    total = sum(n["valor_cop"] for n in nuevas)
    assert abs(total - base) < 5.0           # la suma vuelve al 100%
    porcs = {n["proyecto_inversionista_id"]: n["porcentaje"] for n in nuevas}
    assert porcs == {15: 26.0, 16: 12.0, 17: 62.0}


# ── Panel sano: NO se toca (preserva ediciones) y la re-división es idempotente ────

def test_panel_sano_no_se_redivide():
    lineas = [
        _linea("ingresos", "Ingreso Bruto", 1, 50.0, 30_000_000.0, 0),
        _linea("ingresos", "Ingreso Bruto", 2, 50.0, 30_000_000.0, 1),
    ]
    invs = [_inv(1, "A", 50.0), _inv(2, "B", 50.0)]
    assert _division_desactualizada(lineas, invs) is False  # ya correcto → saltar


def test_redivision_idempotente():
    lineas = [
        _linea("ingresos", "Ingreso Bruto", 1, 50.0, 30_000_000.0, 0),
        _linea("ingresos", "Ingreso Bruto", 2, 50.0, 30_000_000.0, 1),
    ]
    invs = [_inv(1, "A", 50.0), _inv(2, "B", 50.0)]
    nuevas = _redividir_lineas(lineas, invs)
    assert sum(n["valor_cop"] for n in nuevas) == 60_000_000.0
    assert all(n["valor_cop"] == 30_000_000.0 for n in nuevas)


# ── Reconstrucción de base con varios conceptos y signos negativos ────────────────

def test_reconstruir_base_conceptos_y_signos():
    lineas = [
        _linea("ingresos", "Ingreso Bruto", 39, 1.0, 1_000_000.0, 0),
        _linea("comercializacion", "Arranque y parada", 39, 1.0, -2_000.0, 1),
        _linea("facturas", "Administracion", 39, 1.0, -5_000.0, 2),
    ]
    bases = _reconstruir_base(lineas)
    by = {b["concepto"]: b["valor"] for b in bases}
    assert abs(by["Ingreso Bruto"] - 100_000_000.0) < 1.0
    assert abs(by["Arranque y parada"] - (-200_000.0)) < 1.0   # signo preservado
    assert abs(by["Administracion"] - (-500_000.0)) < 1.0
