"""Schemas Pydantic del módulo MEM."""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import date, datetime


class IngestionSummary(BaseModel):
    """Resumen del resultado de una ingesta de datos del MEM."""
    records_created: int = 0
    records_updated: int = 0
    records_failed: int = 0
    rows_processed: int = 0
    errors: list[str] = []


class MEMDatosASICOut(BaseModel):
    id: int
    proyecto_id: int
    fecha: date
    hora: int
    generacion_kwh: float
    fuente: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class MEMPrecioBolsaOut(BaseModel):
    id: int
    fecha: date
    hora: int
    precio_cop_kwh: float
    created_at: datetime
    model_config = {"from_attributes": True}


class GesconEstadoUpdate(BaseModel):
    """Actualización manual de estado GESCON (mientras no exista la integración)."""
    proyecto_id: int
    estado: str
    observaciones: Optional[str] = None


class MEMGesconEstadoOut(BaseModel):
    id: int
    proyecto_id: int
    estado: str
    fecha_actualizacion: datetime
    observaciones: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class PreSettlementSummary(BaseModel):
    """Resumen de la generación de pre-liquidaciones para un período."""
    periodo: date
    preliminares_creadas: int = 0
    preliminares_actualizadas: int = 0
    proyectos_sin_datos: int = 0
    errores: list[str] = []


class LiquidacionPreliminarOut(BaseModel):
    id: int
    liquidacion_id: Optional[int] = None
    proyecto_id: int
    periodo: date
    estado: str
    datos_calculados: Optional[dict[str, Any]] = None
    invoice_generated: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}
