"""Tests del merge de costos del ER con los valores del módulo (lógica pura).

El Panel debe tomar Mantenimiento y Arrendamiento del módulo cuando el proyecto
tiene contrato. Aquí se fija ese reemplazo: valor, marca de fuente, recálculo del
IVA derivado y el caso de agregar el concepto cuando el ER no lo traía.
"""
from datetime import date

from app.services.costos_panel import aplicar_costos_modulo, _tarifa_indexada_periodo


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


def test_alias_fondo_de_mantenimiento_no_duplica():
    """El ER trae 'Fondo de mantenimiento' (= Mantenimiento). El override debe
    reemplazar ESA línea (renombrándola) y su IVA, sin agregar una 'Mantenimiento'
    aparte que duplicaría el costo."""
    base = [
        {"grupo": "ingresos", "concepto": "Ingreso Bruto", "valor": 1000.0},
        {"grupo": "costos", "concepto": "Fondo de mantenimiento", "valor": -4204000.0, "hoja": "Sheet1", "celda": "G57"},
        {"grupo": "costos", "concepto": "IVA Fondo de mantenimiento", "valor": -798760.0},
    ]
    mods = {"Mantenimiento": {"valor": -2605807.0, "fuente": "om", "iva": True,
                              "alias": ["Fondo de mantenimiento"]}}
    out = aplicar_costos_modulo(base, mods)
    mant = [l for l in out if l["concepto"] == "Mantenimiento"]
    assert len(mant) == 1 and mant[0]["valor"] == -2605807.0 and mant[0]["fuente"] == "om"
    # No quedó ninguna línea con el nombre viejo (ni base ni IVA).
    assert not any("Fondo de mantenimiento" in l["concepto"] for l in out)
    iva = [l for l in out if l["concepto"] == "IVA Mantenimiento"]
    assert len(iva) == 1 and iva[0]["valor"] == round(-2605807.0 * 0.19, 2)


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


# ── Representación / CGM: grupo 'facturas' (tarifa app × kWh del ER) ─────────────
def _base_facturas():
    return [
        {"grupo": "ingresos", "concepto": "Ingreso Bruto", "valor": 1000.0},
        {"grupo": "facturas", "concepto": "Representación", "valor": -500.0, "hoja": "Sheet1", "celda": "H40"},
        {"grupo": "facturas", "concepto": "CGM", "valor": -500.0, "hoja": "Sheet1", "celda": "H41"},
        {"grupo": "facturas", "concepto": "Administración", "valor": -38.0},
    ]


def test_facturas_reemplaza_repr_y_cgm_sin_tocar_admin():
    mods = {
        "Representación": {"grupo": "facturas", "valor": -526.0, "fuente": "servicios"},
        "CGM": {"grupo": "facturas", "valor": -552.83, "fuente": "servicios"},
    }
    out = aplicar_costos_modulo(_base_facturas(), mods)
    rep = next(l for l in out if l["concepto"] == "Representación")
    cgm = next(l for l in out if l["concepto"] == "CGM")
    admin = next(l for l in out if l["concepto"] == "Administración")
    assert rep["valor"] == -526.0 and rep["fuente"] == "servicios" and rep["grupo"] == "facturas"
    assert cgm["valor"] == -552.83 and cgm["fuente"] == "servicios"
    assert admin["valor"] == -38.0                 # Admin no se toca (sigue del ER)
    assert rep["hoja"] is None                     # ya no viene de una celda del ER


def test_facturas_reemplaza_administracion():
    """Admin viene de tarifa_admin × ingreso (fuente 'operacion'), reemplaza la del ER."""
    mods = {"Administración": {"grupo": "facturas", "valor": -76.0, "fuente": "operacion"}}
    out = aplicar_costos_modulo(_base_facturas(), mods)
    admin = next(l for l in out if l["concepto"] == "Administración")
    assert admin["valor"] == -76.0 and admin["fuente"] == "operacion"


def test_facturas_no_genera_linea_de_iva_guardada():
    """Repr/CGM no guardan IVA (el Panel lo deriva por cliente al leer)."""
    mods = {"Representación": {"grupo": "facturas", "valor": -526.0, "fuente": "servicios"}}
    out = aplicar_costos_modulo(_base_facturas(), mods)
    assert not any(l["concepto"] == "IVA Representación" for l in out)


# ── Tarifa indexada por aniversario ─────────────────────────────────────────────
_IDX = [
    {"año": 2024, "ipc": None, "valor": 5.0, "esBase": True},
    {"año": 2025, "ipc": 5.2, "valor": 5.26},
    {"año": 2026, "ipc": 5.1, "valor": 5.52826},
]
_FIRMA = date(2024, 10, 11)


def test_tarifa_antes_del_aniversario_usa_la_del_ano_anterior():
    # Junio 2026 es ANTES del aniversario (11 oct) → aplica la tarifa de 2025.
    assert _tarifa_indexada_periodo(_IDX, 5.0, _FIRMA, "2026-06") == 5.26


def test_tarifa_despues_del_aniversario_usa_la_nueva():
    # Noviembre 2026 ya pasó el aniversario de oct → tarifa 2026.
    assert _tarifa_indexada_periodo(_IDX, 5.0, _FIRMA, "2026-11") == 5.52826


def test_tarifa_en_ano_base_usa_la_base():
    assert _tarifa_indexada_periodo(_IDX, 5.0, _FIRMA, "2024-12") == 5.0


def test_tarifa_sin_indexacion_cae_a_la_base():
    assert _tarifa_indexada_periodo([], 7.0, _FIRMA, "2026-06") == 7.0
    assert _tarifa_indexada_periodo(None, 7.0, _FIRMA, "2026-06") == 7.0


def test_tarifa_periodo_anterior_a_todo_usa_esbase():
    # Período anterior incluso al año base → cae a la entrada esBase.
    assert _tarifa_indexada_periodo(_IDX, None, _FIRMA, "2023-01") == 5.0


def test_tarifa_soporta_esquema_internet_anio_y_es_base():
    """Internet/O&M usan otro esquema de JSONB: 'anio' (sin ñ) y 'es_base'."""
    idx = [
        {"anio": 2024, "ipc_aplicado": None, "valor": 100000.0, "es_base": True},
        {"anio": 2025, "ipc_aplicado": 5.2, "valor": 105200.0},
    ]
    assert _tarifa_indexada_periodo(idx, None, date(2024, 3, 1), "2025-06") == 105200.0
    assert _tarifa_indexada_periodo(idx, None, date(2024, 3, 1), "2024-06") == 100000.0
    # Antes del año base → esBase/es_base.
    assert _tarifa_indexada_periodo(idx, None, date(2024, 3, 1), "2023-01") == 100000.0
