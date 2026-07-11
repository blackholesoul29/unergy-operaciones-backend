"""Esquemas Pydantic para el pipeline de ingesta de datos XM.

Estos esquemas validan/serializan las filas de `liquidacion_xm_dato`
(ver `app.models.liquidacion_xm.LiquidacionXMDatoIngesta`).
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class LiquidacionXMDatoBase(BaseModel):
    codigo_recurso: str
    fecha: date
    agente: Optional[str] = None
    tipo_recurso: Optional[str] = None
    capacidad_efectiva_neta_mw: Optional[float] = None
    generacion_kwh: Optional[float] = None
    precio_liquidacion_cop_kwh: Optional[float] = None
    valor_liquidacion_cop: Optional[float] = None


class LiquidacionXMDatoCreate(LiquidacionXMDatoBase):
    """Datos listos para persistir: incluyen la procedencia y el hash de integridad."""
    fuente_archivo: str
    hash_fila: str


class LiquidacionXMDato(LiquidacionXMDatoBase):
    """Representación de salida (respuesta de la API)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    fuente_archivo: str
    hash_fila: str
    fecha_ingesta: datetime


class LiquidacionXMDatoPage(BaseModel):
    """Respuesta paginada del listado de datos XM."""
    total: int
    skip: int
    limit: int
    items: list[LiquidacionXMDato]


class IngestionResumen(BaseModel):
    """Resumen devuelto tras procesar un archivo XM."""
    fuente_archivo: str
    file_type: str
    filas_leidas: int
    filas_nuevas: int
    filas_duplicadas: int
    errores: list[str] = []


class IngestionStatus(BaseModel):
    """Metadatos de la última ingesta registrada."""
    ultima_ingesta: Optional[datetime] = None
    fuente_archivo: Optional[str] = None
    total_registros: int = 0
