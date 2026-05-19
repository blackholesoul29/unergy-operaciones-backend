from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, field_validator

TIPOS_GARANTIA = ("cuenta_custodia", "poliza", "carta_credito", "fiducia", "otro")
ESTADOS_GARANTIA = ("vigente", "vencida", "en_renovacion", "liberada", "en_proceso")


class GarantiaBase(BaseModel):
    proyecto_id: Optional[int] = None
    contrato_ppa_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    tipo: Literal["cuenta_custodia", "poliza", "carta_credito", "fiducia", "otro"]
    entidad: Optional[str] = None
    numero_referencia: Optional[str] = None
    valor_cop: float
    porcentaje_cobertura: Optional[float] = None
    fecha_constitucion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    estado: Literal["vigente", "vencida", "en_renovacion", "liberada", "en_proceso"] = "vigente"
    observaciones: Optional[str] = None

    @field_validator("valor_cop")
    @classmethod
    def valor_must_be_positive(cls, v):
        if v < 0:
            raise ValueError("valor_cop must be >= 0")
        return v


class GarantiaCreate(GarantiaBase):
    pass


class GarantiaUpdate(BaseModel):
    proyecto_id: Optional[int] = None
    contrato_ppa_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    tipo: Optional[Literal["cuenta_custodia", "poliza", "carta_credito", "fiducia", "otro"]] = None
    entidad: Optional[str] = None
    numero_referencia: Optional[str] = None
    valor_cop: Optional[float] = None
    porcentaje_cobertura: Optional[float] = None
    fecha_constitucion: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    estado: Optional[Literal["vigente", "vencida", "en_renovacion", "liberada", "en_proceso"]] = None
    observaciones: Optional[str] = None


class GarantiaOut(GarantiaBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    proyecto_nombre: Optional[str] = None
    contrato_nombre: Optional[str] = None


class MovimientoBase(BaseModel):
    tipo: Literal["deposito", "cobro_xm", "devolucion", "ajuste", "interes", "renovacion"]
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
