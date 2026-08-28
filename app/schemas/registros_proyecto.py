"""Schemas Pydantic v2 de la seccion "Registros" (expediente documental)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------
class ArchivoCreate(BaseModel):
    url: str
    nombre_archivo: Optional[str] = None
    origen: str = "LINK"
    drive_file_id: Optional[str] = None
    tamano_bytes: Optional[int] = None
    tipo_mime: Optional[str] = None


class ArchivoOut(BaseModel):
    id: int
    documento_id: int
    origen: str
    url: str
    nombre_archivo: Optional[str] = None
    drive_file_id: Optional[str] = None
    tamano_bytes: Optional[int] = None
    tipo_mime: Optional[str] = None
    subido_por: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Documentos (casillas del expediente)
# ---------------------------------------------------------------------------
class DocumentoUpdate(BaseModel):
    estado: Optional[str] = None
    radicado: Optional[str] = None
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    emisor: Optional[str] = None
    notas: Optional[str] = None


class DocumentoOut(BaseModel):
    id: int
    proyecto_id: int
    proceso: str
    item_codigo: str
    estado: str
    radicado: Optional[str] = None
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    emisor: Optional[str] = None
    notas: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    archivos: list[ArchivoOut] = []
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
class ParametroValor(BaseModel):
    """Un valor a guardar. `equipo_tipo`/`equipo_posicion` solo para datos de equipo."""

    clave: str
    valor: Optional[str] = None
    equipo_tipo: Optional[str] = None
    equipo_posicion: Optional[int] = None
    documento_origen_id: Optional[int] = None
    verificado: Optional[bool] = None
    notas: Optional[str] = None


class ParametrosGuardar(BaseModel):
    valores: list[ParametroValor] = Field(default_factory=list)


class ParametroOut(BaseModel):
    id: int
    proyecto_id: int
    clave: str
    equipo_tipo: str
    equipo_posicion: int
    valor: Optional[str] = None
    valor_fecha: Optional[date] = None
    documento_origen_id: Optional[int] = None
    verificado: bool = False
    notas: Optional[str] = None
    actualizado_por: Optional[str] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Vistas compuestas
# ---------------------------------------------------------------------------
class CampoFormulario(BaseModel):
    clave: str
    titulo: str
    tipo: str
    unidad: str = ""
    grupo: str
    grupo_etiqueta: str
    requerido: bool = False
    columnas: Optional[list[str]] = None
    equipo_tipo: str = ""
    equipo_posicion: int = 0
    equipo_etiqueta: str = ""
    valor: Optional[str] = None
    verificado: bool = False
    documento_origen_id: Optional[int] = None
    diligenciado_en_otro_documento: bool = False
    tambien_en: list[dict[str, Any]] = []


class FormularioItemOut(BaseModel):
    documento: DocumentoOut
    item: dict[str, Any]
    campos: list[CampoFormulario]
    total_campos: int
    campos_diligenciados: int
    model_config = ConfigDict(from_attributes=True)


class ItemResumen(BaseModel):
    proceso: str
    codigo: str
    titulo: str
    descripcion: str = ""
    emisor: str = ""
    multiple: bool = False
    estado_base: str
    nota_catalogo: Optional[str] = None
    documento_id: Optional[int] = None
    estado: str
    radicado: Optional[str] = None
    fecha_emision: Optional[date] = None
    archivos: int = 0
    parametros_esperados: int = 0
    parametros_diligenciados: int = 0


class ProcesoResumen(BaseModel):
    proceso: str
    etiqueta: str
    items: list[ItemResumen]
    total_items: int
    items_cargados: int
    avance_pct: int


class ResumenProyectoOut(BaseModel):
    proyecto_id: int
    nombre_comercial: str
    codigo_cnd: Optional[str] = None
    procesos: list[ProcesoResumen]
    parametros_diligenciados: int
    parametros_totales: int
