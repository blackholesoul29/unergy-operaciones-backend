"""Schemas para registros de gestión de proyectos (``gestion_registros``).

La tabla ya existe en el modelo (``app.models.gestion.GestionRegistro``) pero aún
no expone endpoints CRUD. Estos schemas dejan lista la validación estricta del
JSONB ``archivos_json`` para cuando se añadan, y son reutilizables desde
cualquier endpoint futuro.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from app.models.gestion import TipoGestionEnum
from app.schemas.jsonb_validators import ArchivoJsonSchema, validate_archivos_json


class GestionRegistroCreate(BaseModel):
    proyecto_id: int
    tipo: TipoGestionEnum
    titulo: str
    descripcion: Optional[str] = None
    # Lista de adjuntos validada contra ArchivoJsonSchema (nombre + url http/https).
    archivos_json: Optional[list[ArchivoJsonSchema]] = None

    @field_validator("archivos_json", mode="before")
    @classmethod
    def _validar_archivos(cls, v: Any) -> Any:
        return validate_archivos_json(v)


class GestionRegistroUpdate(BaseModel):
    tipo: Optional[TipoGestionEnum] = None
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    archivos_json: Optional[list[ArchivoJsonSchema]] = None

    @field_validator("archivos_json", mode="before")
    @classmethod
    def _validar_archivos(cls, v: Any) -> Any:
        return validate_archivos_json(v)


class GestionRegistroOut(BaseModel):
    id: int
    proyecto_id: int
    tipo: TipoGestionEnum
    titulo: str
    descripcion: Optional[str] = None
    archivos_json: Optional[list[Any]] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


__all__ = [
    "GestionRegistroCreate",
    "GestionRegistroUpdate",
    "GestionRegistroOut",
]
