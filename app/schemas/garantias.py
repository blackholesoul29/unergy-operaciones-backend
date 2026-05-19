from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class GarantiaBase(BaseModel):
    proyecto_id: Optional[int] = None
    contrato_ppa_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    tipo: str
    entidad: Optional[str] = None
    numero_referencia: Optional[str] = None
    valor_cop: float
    porcentaje_cobertura: Optional[float] = None
    fecha_constitucion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    estado: str = "vigente"
    observaciones: Optional[str] = None


class GarantiaCreate(GarantiaBase):
    pass


class GarantiaUpdate(BaseModel):
    proyecto_id: Optional[int] = None
    contrato_ppa_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    tipo: Optional[str] = None
    entidad: Optional[str] = None
    numero_referencia: Optional[str] = None
    valor_cop: Optional[float] = None
    porcentaje_cobertura: Optional[float] = None
    fecha_constitucion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    estado: Optional[str] = None
    observaciones: Optional[str] = None


class GarantiaOut(GarantiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    proyecto_nombre: Optional[str] = None
    contrato_nombre: Optional[str] = None


class MovimientoBase(BaseModel):
    tipo: str
    monto_cop: float
    fecha: date
    concepto: Optional[str] = None
    referencia_xm: Optional[str] = None


class MovimientoCreate(MovimientoBase):
    pass


class MovimientoOut(MovimientoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    garantia_id: int
    saldo_posterior_cop: Optional[float] = None
    created_at: datetime
