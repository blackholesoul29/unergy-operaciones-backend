"""Tests unitarios para el servicio de división de PDF O&M."""
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.services.om_pdf_splitter import (
    extraer_datos_pagina,
    match_proyecto,
    detectar_paginas,
    extraer_pagina_datos,
    escribir_o_anexar_pagina,
    _nombre_distintivo,
    _normalizar,
    _parse_monto,
)


def _pdf_con_texto(paginas_texto: list[str]) -> bytes:
    """Genera un PDF sintético con una página por cada texto (sin acentos —
    la codificación Latin-1 del content stream de prueba no los necesita)."""
    writer = PdfWriter()
    for texto in paginas_texto:
        page = writer.add_blank_page(width=612, height=792)
        content = f"BT /F1 12 Tf 50 700 Td ({texto}) Tj ET".encode("latin-1")
        stream = DecodedStreamObject()
        stream.set_data(content)
        stream_ref = writer._add_object(stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Contents")] = stream_ref
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


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


# ── Colisión de substring (bug real: "Chiriguaná 2" es substring de "Chiriguaná 24") ─────

_CONTRATOS_COLISION = [
    {"contrato_id": 10, "nombre_proyecto": "MGS 0010 Chiriguaná 2"},
    {"contrato_id": 11, "nombre_proyecto": "MGS 0011 Chiriguaná 24"},
]

def test_match_colision_substring_no_adivina():
    # "chiriguana 2" es substring de "chiriguana 24" → ambiguo, no debe asignarse
    # ni al contrato 10 ni al 11 sin revisión manual.
    cid, ratio = match_proyecto("Minigranja Solar Chiriguaná 2", _CONTRATOS_COLISION)
    assert cid is None
    assert ratio < 0

def test_match_colision_no_afecta_caso_no_ambiguo():
    # Sin el segundo contrato en colisión, el match único sigue funcionando igual.
    cid, ratio = match_proyecto("Minigranja Solar Chiriguaná 2", _CONTRATOS_COLISION[:1])
    assert cid == 10
    assert ratio == 1.0


# ── detectar_paginas (solo detección, sin escritura) ─────────────────────────

_CONTRATOS_DETECCION = [
    {"contrato_id": 1, "nombre_proyecto": "MGS 0001 Uruaco"},
]

def test_detectar_paginas_separa_asignadas_y_sin_match(tmp_path):
    pdf_bytes = _pdf_con_texto([
        "Mantenimiento Preventivo - Minigranja Solar Uruaco - Junio",
        "Texto irreconocible sin ningun proyecto SOLENIUM SAS",
    ])
    ruta = tmp_path / "consolidado.pdf"
    ruta.write_bytes(pdf_bytes)

    resultado = detectar_paginas(ruta, _CONTRATOS_DETECCION)

    assert list(resultado["asignadas"].keys()) == [1]
    indices, _datos = resultado["asignadas"][1]
    assert indices == [0]
    assert len(resultado["sin_match"]) == 1
    assert resultado["sin_match"][0]["pagina"] == 2
    assert resultado["sin_match"][0]["razon"] == "no_se_extrajo_nombre"

def test_detectar_paginas_no_escribe_ningun_archivo(tmp_path):
    pdf_bytes = _pdf_con_texto(["Mantenimiento Preventivo - Minigranja Solar Uruaco - Junio"])
    ruta = tmp_path / "consolidado.pdf"
    ruta.write_bytes(pdf_bytes)

    detectar_paginas(ruta, _CONTRATOS_DETECCION)

    assert list(tmp_path.iterdir()) == [ruta]  # nada nuevo se creó


# ── extraer_pagina_datos (metadata de una página aislada) ────────────────────

def test_extraer_pagina_datos_toma_solo_la_pagina_pedida(tmp_path):
    pdf_bytes = _pdf_con_texto([
        "Mantenimiento Preventivo - Minigranja Solar Uruaco - Junio",
        "Mantenimiento Preventivo - Minigranja Solar Gandalf - Junio",
    ])
    ruta = tmp_path / "consolidado.pdf"
    ruta.write_bytes(pdf_bytes)

    datos_pag2 = extraer_pagina_datos(ruta, 2)
    assert datos_pag2["nombre_proyecto"] == "Minigranja Solar Gandalf"

    datos_pag1 = extraer_pagina_datos(ruta, 1)
    assert datos_pag1["nombre_proyecto"] == "Minigranja Solar Uruaco"


# ── escribir_o_anexar_pagina (usado en asignación manual) ────────────────────

def test_escribir_o_anexar_pagina_crea_archivo_nuevo(tmp_path):
    origen = tmp_path / "consolidado.pdf"
    origen.write_bytes(_pdf_con_texto(["Página única"]))
    salida = tmp_path / "individual.pdf"

    escribir_o_anexar_pagina(origen, 1, salida)

    assert salida.exists()
    assert len(PdfReader(str(salida)).pages) == 1

def test_escribir_o_anexar_pagina_anexa_si_ya_existe(tmp_path):
    origen = tmp_path / "consolidado.pdf"
    origen.write_bytes(_pdf_con_texto(["Página uno", "Página dos"]))
    salida = tmp_path / "individual.pdf"

    # Simula que el contrato ya tenía un documento con la página 1 (de un match
    # automático previo) y ahora se le asigna manualmente también la página 2.
    escribir_o_anexar_pagina(origen, 1, salida)
    escribir_o_anexar_pagina(origen, 2, salida)

    assert len(PdfReader(str(salida)).pages) == 2
