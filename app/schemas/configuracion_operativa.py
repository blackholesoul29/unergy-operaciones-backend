from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.configuracion_operativa import TipoParametroConfigEnum


class ConfiguracionOperativaCreate(BaseModel):
    # proyecto_id None → configuración global (aplica a cualquier proyecto).
    proyecto_id: Optional[int] = None
    tipo_parametro: TipoParametroConfigEnum
    valor_float: float
    unidad: str
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: bool = True

    @field_validator("valor_float")
    @classmethod
    def _valor_no_negativo(cls, v: float) -> float:
        if v < 0:
            raise ValueError("valor_float no puede ser negativo")
        return v


class ConfiguracionOperativaUpdate(BaseModel):
    """Actualización parcial: solo se aplican los campos presentes."""
    valor_float: Optional[float] = None
    unidad: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: Optional[bool] = None

    @field_validator("valor_float")
    @classmethod
    def _valor_no_negativo(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("valor_float no puede ser negativo")
        return v


class ConfiguracionOperativaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proyecto_id: Optional[int] = None
    proyecto_nombre: Optional[str] = None
    tipo_parametro: str
    valor_float: float
    unidad: str
    fecha_inicio: datetime
    fecha_fin: Optional[datetime] = None
    activo: bool
