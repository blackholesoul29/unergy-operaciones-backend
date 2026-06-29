"""Tests de los validadores estrictos de columnas JSONB.

Cubren el contrato que usan los endpoints de fallas (fotos_urls) y los schemas
de gestión (archivos_json): aceptar las formas válidas (objeto y URL legada) y
rechazar URLs inválidas o estructura faltante con un mensaje claro.
"""
import pytest

from app.schemas.jsonb_validators import (
    ArchivoJsonSchema,
    FotoUrlSchema,
    validate_archivos_json,
    validate_fotos_urls,
)


# ── fotos_urls ───────────────────────────────────────────────────────────────

def test_fotos_urls_none_ok():
    assert validate_fotos_urls(None) is None


def test_fotos_urls_lista_de_objetos_ok():
    data = [{
        "id": "abc",
        "nombre": "foto.jpg",
        "url": "https://drive.google.com/file/d/XYZ/view",
        "tamaño": 1234,
        "tipo_mime": "image/jpeg",
        "created_at": "2026-06-29T00:00:00Z",
    }]
    assert validate_fotos_urls(data) == data


def test_fotos_urls_strings_legados_ok():
    # URL simple y formato legado "url#nombre".
    data = [
        "https://drive.google.com/file/d/XYZ/view",
        "https://drive.google.com/file/d/XYZ/view#foto.jpg",
    ]
    assert validate_fotos_urls(data) == data


def test_fotos_urls_url_invalida_falla():
    with pytest.raises(ValueError) as exc:
        validate_fotos_urls(["not-a-url"])
    assert "fotos_urls[0]" in str(exc.value)


def test_fotos_urls_objeto_sin_url_falla():
    with pytest.raises(ValueError) as exc:
        validate_fotos_urls([{"nombre": "foto.jpg"}])
    assert "fotos_urls[0]" in str(exc.value)


def test_fotos_urls_objeto_url_invalida_falla():
    with pytest.raises(ValueError):
        validate_fotos_urls([{"url": "ftp://x"}])


def test_fotos_urls_no_lista_falla():
    with pytest.raises(ValueError):
        validate_fotos_urls("https://x.com")


def test_foto_url_schema_acepta_campos_extra():
    m = FotoUrlSchema.model_validate({"url": "https://x.com/a", "otro": 1})
    assert m.url == "https://x.com/a"


# ── archivos_json ────────────────────────────────────────────────────────────

def test_archivos_json_none_ok():
    assert validate_archivos_json(None) is None


def test_archivos_json_lista_ok():
    data = [{"nombre": "doc.pdf", "url": "https://x.com/doc.pdf"}]
    assert validate_archivos_json(data) == data


def test_archivos_json_falta_nombre_falla():
    with pytest.raises(ValueError) as exc:
        validate_archivos_json([{"url": "https://x.com/doc.pdf"}])
    assert "archivos_json[0]" in str(exc.value)


def test_archivos_json_url_invalida_falla():
    with pytest.raises(ValueError) as exc:
        validate_archivos_json([{"nombre": "doc.pdf", "url": "nope"}])
    assert "archivos_json[0]" in str(exc.value)


def test_archivos_json_elemento_no_objeto_falla():
    with pytest.raises(ValueError):
        validate_archivos_json(["https://x.com/doc.pdf"])


def test_archivo_json_schema_directo():
    m = ArchivoJsonSchema.model_validate({"nombre": "d", "url": "http://a.io/x"})
    assert m.nombre == "d"
