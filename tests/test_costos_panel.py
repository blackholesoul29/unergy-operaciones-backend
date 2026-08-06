"""Tests del merge de costos del ER con los valores del módulo (lógica pura).

El Panel debe tomar Mantenimiento y Arrendamiento del módulo cuando el proyecto
tiene contrato. Aquí se fija ese reemplazo: valor, marca de fuente, recálculo del
IVA derivado y el caso de agregar el concepto cuando el ER no lo traía.
"""
from app.services.costos_panel import aplicar_costos_modulo


def _base():
    # Líneas típicas del ER (costos son negativos; el IVA de mantenimiento va aparte).
    return [
        {"grupo": "ingresos", "concepto": "Ingreso Bruto", "valor": 1000.0, "hoja": "Sheet1", "celda": "H10"},
        {"grupo": "costos", "concepto": "Arrendamiento", "valor": -100.0, "hoja": "Sheet1", "celda": "H35"},
        {"grupo": "costos", "concepto": "Mantenimiento", "valor": -200.0, "hoja": "Sheet1", "celda": "H36"},
        {"grupo": "costos", "concepto": "IVA Mantenimiento", "valor": -38.0, "hoja": None, "celda": None},
    ]


def test_reemplaza_valor_y_marca_fuente():
    mods = {
        "Arrendamiento": {"valor": -111.0, "fuente": "arriendos", "iva": False},
        "Mantenimiento": {"valor": -300.0, "fuente": "om", "iva": True},
    }
    out = aplicar_costos_modulo(_base(), mods)
    arr = next(l for l in out if l["concepto"] == "Arrendamiento")
    man = next(l for l in out if l["concepto"] == "Mantenimiento")
    assert arr["valor"] == -111.0 and arr["fuente"] == "arriendos"
    assert man["valor"] == -300.0 and man["fuente"] == "om"
    # El origen del ER se borra: ya no viene de una celda.
    assert arr["hoja"] is None and arr["celda"] is None


def test_recalcula_iva_de_mantenimiento():
    mods = {"Mantenimiento": {"valor": -300.0, "fuente": "om", "iva": True}}
    out = aplicar_costos_modulo(_base(), mods, iva=0.19)
    iva = next(l for l in out if l["concepto"] == "IVA Mantenimiento")
    assert iva["valor"] == -57.0            # 300 × 0.19, con signo
    assert iva["fuente"] == "om"


def test_arriendo_sin_iva_no_genera_linea():
    """Arrendador NO responsable de IVA: el módulo manda iva_valor=None → sin línea."""
    mods = {"Arrendamiento": {"valor": -111.0, "fuente": "arriendos", "iva_valor": None}}
    out = aplicar_costos_modulo(_base(), mods)
    assert not any(l["concepto"] == "IVA Arrendamiento" for l in out)


def test_arriendo_con_iva_del_modulo():
    """Arrendador responsable de IVA: el IVA lo trae el módulo (no un 19% plano),
    con el monto exacto que calculó."""
    mods = {"Arrendamiento": {"valor": -111.0, "fuente": "arriendos", "iva_valor": -21.09}}
    out = aplicar_costos_modulo(_base(), mods)
    iva = next(l for l in out if l["concepto"] == "IVA Arrendamiento")
    assert iva["valor"] == -21.09 and iva["fuente"] == "arriendos"
    assert out.index(iva) == out.index(next(l for l in out if l["concepto"] == "Arrendamiento")) + 1


def test_iva_valor_none_elimina_iva_previo_del_er():
    """Si el ER traía 'IVA Arrendamiento' pero el módulo dice que no lleva, se quita."""
    base = _base() + [{"grupo": "costos", "concepto": "IVA Arrendamiento", "valor": -19.0}]
    mods = {"Arrendamiento": {"valor": -100.0, "fuente": "arriendos", "iva_valor": None}}
    out = aplicar_costos_modulo(base, mods)
    assert not any(l["concepto"] == "IVA Arrendamiento" for l in out)


def test_agrega_concepto_si_el_er_no_lo_traia():
    """El ER no tenía mantenimiento pero el proyecto sí tiene contrato: se agrega
    la línea (y su IVA), no se pierde el costo."""
    base = [{"grupo": "ingresos", "concepto": "Ingreso Bruto", "valor": 1000.0}]
    mods = {"Mantenimiento": {"valor": -300.0, "fuente": "om", "iva": True}}
    out = aplicar_costos_modulo(base, mods)
    man = next(l for l in out if l["concepto"] == "Mantenimiento")
    iva = next(l for l in out if l["concepto"] == "IVA Mantenimiento")
    assert man["valor"] == -300.0 and man["fuente"] == "om"
    assert iva["valor"] == -57.0
    # El IVA queda inmediatamente después de su concepto.
    assert out.index(iva) == out.index(man) + 1


def test_no_muta_la_entrada():
    base = _base()
    antes = [dict(l) for l in base]
    aplicar_costos_modulo(base, {"Mantenimiento": {"valor": -300.0, "fuente": "om", "iva": True}})
    assert base == antes


def test_sin_mods_devuelve_las_mismas_lineas():
    base = _base()
    out = aplicar_costos_modulo(base, {})
    assert out == base
