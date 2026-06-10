from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class CostoVariableCreate(BaseModel):
    proyecto_id: int
    tipo_accion: str
    tipo_equipo: str
    monto: float
    fecha: date
    descripcion: str
    observaciones: Optional[str] = None


class CostoVariableUpdate(BaseModel):
    tipo_accion: Optional[str] = None
    tipo_equipo: Optional[str] = None
    monto: Optional[float] = None
    fecha: Optional[date] = None
    descripcion: Optional[str] = None
    observaciones: Optional[str] = None


class CostoVariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proyecto_id: int
    proyecto_nombre: Optional[str] = None
    tipo_accion: str
    tipo_equipo: str
    monto: float
    fecha: date
    descripcion: str
    observaciones: Optional[str] = None

    url_factura: Optional[str] = None
    nombre_factura: Optional[str] = None
    url_cotizacion: Optional[str] = None
    nombre_cotizacion: Optional[str] = None
    url_rut: Optional[str] = None
    nombre_rut: Optional[str] = None
    url_certificado_bancario: Optional[str] = None
    nombre_certificado_bancario: Optional[str] = None

    documentos_completos: bool = False

    created_at: datetime
    updated_at: datetime
