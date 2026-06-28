"""Invariante de compatibilidad: las descargas reconstruyen la ruta del archivo
desde una base derivada de ``settings.UPLOAD_DIRECTORY``.

Si esa base se aleja del layout en disco histórico (``./uploads/{arriendos,om}``),
TODOS los documentos ya subidos quedan inaccesibles (HTTP 404) tras el deploy,
porque la ruta guardada en BD (``ruta_local``) deja de coincidir.

Este test ancla el contrato para que un cambio futuro no vuelva a romperlo en silencio.
"""
from __future__ import annotations

import pathlib

from app.core.config import settings


def test_upload_directory_default_matches_historic_layout():
    # Debe apuntar al layout ./uploads ya existente y coincidir con STORAGE_LOCAL_PATH
    # (se normaliza porque "uploads" y "./uploads" son la misma carpeta).
    assert pathlib.Path(settings.UPLOAD_DIRECTORY).resolve() == pathlib.Path("uploads").resolve()
    assert (
        pathlib.Path(settings.UPLOAD_DIRECTORY).resolve()
        == pathlib.Path(settings.STORAGE_LOCAL_PATH).resolve()
    )


def test_arriendos_base_lives_under_uploads():
    from app.api.v1.arriendos import _ARR_BASE

    base = pathlib.Path(settings.UPLOAD_DIRECTORY) / "arriendos"
    assert _ARR_BASE == base
    # subdir histórico, no un árbol nuevo tipo ./datos/...
    assert _ARR_BASE.parts[-2:] == ("uploads", "arriendos")


def test_om_base_lives_under_uploads():
    from app.api.v1.om import _OM_BASE

    base = pathlib.Path(settings.UPLOAD_DIRECTORY) / "om"
    assert _OM_BASE == base
    assert _OM_BASE.parts[-2:] == ("uploads", "om")
