"""Tests unitarios para el servicio de división de PDF O&M."""
import pytest


def test_extraer_nombre_una_linea():
    from app.services.om_pdf_splitter import extraer_nombre_pagina
    texto = "Mantenimiento Preventivo - Minigranja Solar Uruaco - Junio"
    assert extraer_nombre_pagina(texto) == "Minigranja Solar Uruaco"


def test_extraer_nombre_multilinea():
    from app.services.om_pdf_splitter import extraer_nombre_pagina
    texto = "Mantenimiento\nPreventivo - Minigranja\nSolar Uruaco - Junio"
    assert extraer_nombre_pagina(texto) == "Minigranja Solar Uruaco"


def test_extraer_nombre_no_encontrado():
    from app.services.om_pdf_splitter import extraer_nombre_pagina
    texto = "Factura sin descripción estándar"
    assert extraer_nombre_pagina(texto) is None


def test_match_proyecto_exacto():
    from app.services.om_pdf_splitter import match_proyecto
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
        {"contrato_id": 2, "nombre_proyecto": "Minigranja Solar Cañahuate"},
    ]
    assert match_proyecto("Minigranja Solar Uruaco", contratos) == 1


def test_match_proyecto_con_tilde():
    from app.services.om_pdf_splitter import match_proyecto
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
        {"contrato_id": 2, "nombre_proyecto": "Minigranja Solar Cañahuate"},
    ]
    # El PDF puede no tener tilde; el match igual debe funcionar
    assert match_proyecto("Minigranja Solar Canahuate", contratos) == 2


def test_match_proyecto_sin_match():
    from app.services.om_pdf_splitter import match_proyecto
    contratos = [
        {"contrato_id": 1, "nombre_proyecto": "Minigranja Solar Uruaco"},
    ]
    assert match_proyecto("Proyecto Completamente Diferente XYZ", contratos) is None


def test_match_proyecto_lista_vacia():
    from app.services.om_pdf_splitter import match_proyecto
    assert match_proyecto("Minigranja Solar Uruaco", []) is None
