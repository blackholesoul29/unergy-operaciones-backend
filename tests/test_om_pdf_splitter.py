"""Tests unitarios para el servicio de división de PDF O&M."""
from decimal import Decimal
from app.services.om_pdf_splitter import (
    extraer_datos_pagina,
    match_proyecto,
    _nombre_distintivo,
    _normalizar,
    _parse_monto,
)


# ── _nombre_distintivo ────────────────────────────────────────────────────────

def test_distintivo_quita_minigranja_solar():
    assert _nombre_distintivo("Minigranja Solar Uruaco") == "Uruaco"

def test_distintivo_quita_mini_granja_con_espacio():
    assert _nombre_distintivo("Mini granja Solar La Paz") == "La Paz"

def test_distintivo_quita_mgs_codigo():
    assert _nombre_distintivo("MGS 0005 Cañahuate") == "Cañahuate"

def test_distintivo_sin_prefijo_queda_igual():
    assert _nombre_distintivo("Nestlé") == "Nestlé"


# ── _parse_monto ──────────────────────────────────────────────────────────────

def test_parse_monto_con_puntos_miles():
    # "4.500.000,00" → 4500000.00
    assert _parse_monto("4.500.000,00") == Decimal("4500000.00")

def test_parse_monto_sin_decimales():
    assert _parse_monto("855000") == Decimal("855000")

def test_parse_monto_none():
    assert _parse_monto(None) is None


# ── extraer_datos_pagina ──────────────────────────────────────────────────────

_PAGINA_EJEMPLO = """
Factura Electrónica de Venta No. SOFV993
Fecha de facturación: 24-06-2026
CUFE: abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef12

Descripción: Mantenimiento Preventivo - Minigranja Solar Cañahuate - Junio

Total sin impuestos $4.500.000,00
IVA $855.000,00
Total a pagar $5.355.000,00
"""

def test_extraer_nombre_desde_mantenimiento_preventivo():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["nombre_proyecto"] == "Minigranja Solar Cañahuate"
    assert datos["estrategia"] == "mantenimiento_preventivo"

def test_extraer_numero_factura():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["numero_factura"] == "SOFV993"

def test_extraer_total_sin_impuestos():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["total_sin_impuestos"] == Decimal("4500000.00")

def test_extraer_iva():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["iva"] == Decimal("855000.00")

def test_extraer_total_pagar():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["total_pagar"] == Decimal("5355000.00")

def test_extraer_fecha_iso():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["fecha_facturacion"] == "2026-06-24"

def test_extraer_cufe():
    datos = extraer_datos_pagina(_PAGINA_EJEMPLO)
    assert datos["cufe"] is not None
    assert len(datos["cufe"]) >= 40

def test_extraer_nombre_la_paz_verso():
    texto = "Mantenimiento Preventivo - Minigranja Solar La Paz Verso - Junio"
    datos = extraer_datos_pagina(texto)
    assert datos["nombre_proyecto"] == "Minigranja Solar La Paz Verso"

def test_extraer_nombre_nestle():
    texto = "Mantenimiento Preventivo - Nestlé - Junio"
    datos = extraer_datos_pagina(texto)
    assert datos["nombre_proyecto"] == "Nestlé"

def test_extraer_fallback_autorretenedores():
    texto = "Sin descripción mantenimiento\nAUTORRETENEDORES ICA MEDELLIN - Minigranja Solar Merengue - Junio"
    datos = extraer_datos_pagina(texto)
    assert datos["nombre_proyecto"] == "Minigranja Solar Merengue"
    assert datos["estrategia"] == "autorretenedores"

def test_extraer_pagina_sin_match():
    texto = "Solo encabezado sin descripción útil SOLENIUM SAS"
    datos = extraer_datos_pagina(texto)
    assert datos["nombre_proyecto"] is None


# ── match_proyecto ────────────────────────────────────────────────────────────

_CONTRATOS = [
    {"contrato_id": 1, "nombre_proyecto": "MGS 0001 Uruaco"},
    {"contrato_id": 2, "nombre_proyecto": "MGS 0005 Cañahuate"},
    {"contrato_id": 3, "nombre_proyecto": "MGS 0007 La Paz Vallenata"},
    {"contrato_id": 4, "nombre_proyecto": "MGS 0004 Valle de Gandalf"},
    {"contrato_id": 5, "nombre_proyecto": "Nestlé Colombia"},
]

def test_match_minigranja_solar_uruaco():
    cid, ratio = match_proyecto("Minigranja Solar Uruaco", _CONTRATOS)
    assert cid == 1

def test_match_minigranja_solar_canahuate_sin_tilde():
    # PDF puede no tener tilde
    cid, ratio = match_proyecto("Minigranja Solar Canahuate", _CONTRATOS)
    assert cid == 2

def test_match_gandalf_como_substring():
    # "Gandalf" aparece en "MGS 0004 Valle de Gandalf"
    cid, ratio = match_proyecto("Minigranja Solar Gandalf", _CONTRATOS)
    assert cid == 4

def test_match_la_paz_vallenata():
    cid, ratio = match_proyecto("Minigranja Solar La Paz Vallenata", _CONTRATOS)
    assert cid == 3

def test_match_nestle():
    cid, ratio = match_proyecto("Nestlé", _CONTRATOS)
    assert cid == 5

def test_match_sin_resultado():
    cid, ratio = match_proyecto("Proyecto Completamente Diferente XYZ", _CONTRATOS)
    assert cid is None

def test_match_lista_vacia():
    cid, ratio = match_proyecto("Minigranja Solar Uruaco", [])
    assert cid is None
    assert ratio == 0.0
