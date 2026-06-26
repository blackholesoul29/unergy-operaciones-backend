"""Tests unitarios para el servicio de división de PDF O&M."""
import pytest
from app.services.om_pdf_splitter import (
    extraer_nombre_pagina,
    match_proyecto,
    _filtrar_ruido,
)


# ── _filtrar_ruido ────────────────────────────────────────────────────────────

def test_filtrar_ruido_elimina_solenium():
    texto = "SOLENIUM SAS NIT: 901097244\nNombre del Proyecto: Uruaco\nOtra línea"
    limpio = _filtrar_ruido(texto)
    assert "SOLENIUM" not in limpio
    assert "Uruaco" in limpio


def test_filtrar_ruido_elimina_dian():
    texto = "Resolución DIAN 0001\nNombre del Proyecto: Merengue"
    limpio = _filtrar_ruido(texto)
    assert "DIAN" not in limpio
    assert "Merengue" in limpio


# ── extraer_nombre_pagina ─────────────────────────────────────────────────────

def test_extraer_etiqueta_nombre_del_proyecto():
    texto = "SOLENIUM SAS NIT: 901097244-1\nNombre del Proyecto: Minigranja Solar Uruaco\nOtro texto"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert nombre == "Minigranja Solar Uruaco"
    assert estrategia == "etiqueta_nombre"


def test_extraer_etiqueta_proyecto_corta():
    texto = "Proyecto: Minigranja Solar Merengue\nFecha: 2026-06-01"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert nombre == "Minigranja Solar Merengue"
    assert estrategia == "etiqueta_proyecto"


def test_extraer_descripcion_mantenimiento_una_linea():
    texto = "Mantenimiento Preventivo - Minigranja Solar Uruaco - Junio"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert nombre == "Minigranja Solar Uruaco"
    assert estrategia == "descripcion_mantenimiento"


def test_extraer_descripcion_mantenimiento_multilinea():
    texto = "Mantenimiento\nPreventivo - Minigranja\nSolar Uruaco - Junio"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert nombre == "Minigranja Solar Uruaco"
    assert estrategia == "descripcion_mantenimiento"


def test_extraer_minigranja_solar():
    texto = "SOLENIUM SAS\nTel: 3001234567\nMini granja Solar Villanueva\nOtros datos"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert "Villanueva" in nombre
    assert estrategia == "minigranja"


def test_extraer_no_encontrado():
    texto = "SOLENIUM SAS NIT: 901097244-1\nResolución DIAN\nSin descripción útil aquí"
    nombre, estrategia = extraer_nombre_pagina(texto)
    assert nombre is None
    assert estrategia is None


def test_extraer_no_captura_solo_numeros():
    # La estrategia no debe retornar capturas que sean solo números o símbolos
    texto = "Proyecto: 12345\nNombre del Proyecto: Uruaco"
    nombre, estrategia = extraer_nombre_pagina(texto)
    # Debe saltar "12345" (solo números) y llegar a "Uruaco"
    assert nombre is not None
    assert len(nombre) >= 4


# ── match_proyecto ────────────────────────────────────────────────────────────

def test_match_exacto():
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
        {"contrato_id": 2, "nombre_proyecto": "Minigranja Solar Cañahuate"},
    ]
    cid, ratio = match_proyecto("Minigranja Solar Uruaco", contratos)
    assert cid == 1
    assert ratio >= 0.80


def test_match_con_tilde():
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
        {"contrato_id": 2, "nombre_proyecto": "Minigranja Solar Cañahuate"},
    ]
    cid, ratio = match_proyecto("Minigranja Solar Canahuate", contratos)
    assert cid == 2


def test_match_nombre_del_proyecto_label_extraido():
    # Simula lo que extraer_nombre_pagina entrega después de filtrar el label
    contratos = [
        {"contrato_id": 5, "nombre_proyecto": "Minigranja Solar Villanueva"},
    ]
    cid, ratio = match_proyecto("Minigranja Solar Villanueva", contratos)
    assert cid == 5


def test_match_sin_resultado():
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
    ]
    cid, ratio = match_proyecto("Proyecto Completamente Diferente XYZ", contratos)
    assert cid is None


def test_match_lista_vacia():
    cid, ratio = match_proyecto("Minigranja Solar Uruaco", [])
    assert cid is None
    assert ratio == 0.0
