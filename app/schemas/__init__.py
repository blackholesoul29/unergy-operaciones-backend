"""Schemas Pydantic del backend de operaciones.

Re-exporta los validadores de columnas JSONB y los schemas de gestión para que
puedan importarse desde ``app.schemas`` directamente.
"""
from app.schemas.jsonb_validators import (
    ArchivoJsonSchema,
    FotoUrlSchema,
    validate_archivos_json,
    validate_fotos_urls,
)
from app.schemas.gestion import (
    GestionRegistroCreate,
    GestionRegistroOut,
    GestionRegistroUpdate,
)

__all__ = [
    "ArchivoJsonSchema",
    "FotoUrlSchema",
    "validate_archivos_json",
    "validate_fotos_urls",
    "GestionRegistroCreate",
    "GestionRegistroOut",
    "GestionRegistroUpdate",
]
