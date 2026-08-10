from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class VerificacionCostoBase(BaseModel):
    costos_generador: Optional[float] = None
    costos_comercializador: Optional[float] = None
    ac_power: Optional[float] = None


class VerificacionCostoCreate(VerificacionCostoBase):
    proyecto_id: int


class VerificacionCostoUpdate(VerificacionCostoBase):
    pass


class VerificacionCostoOut(VerificacionCostoBase):
    id: int
    proyecto_id: int
    proyecto_nombre: str = ""
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}
