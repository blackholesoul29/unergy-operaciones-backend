from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.configuracion_operativa import TipoParametroConfigEnum


def validar_rango_por_tipo(
    tipo: TipoParametroConfigEnum, valor: float,
) -> None:
    """Valida que `valor` esté en el rango físicamente válido para `tipo`.

    Estos valores alimentan la estimación de impacto económico de fallas, así que
    un valor fuera de rango (p. ej. un factor de capacidad > 1 o un precio ≤ 0)
    corrompería silenciosamente todos los cálculos del proyecto. Lanza
    `ValueError` — Pydantic/FastAPI lo traducen a 422.
    """
    if tipo == TipoParametroConfigEnum.CAPACIDAD_SOLAR:
        if not (0 < valor <= 1):
            raise ValueError(
                "CAPACIDAD_SOLAR debe ser un factor entre 0 y 1 (exclusivo/inclusivo)"
            )
    elif tipo == TipoParametroConfigEnum.PRECIO_ENERGIA:
        if valor <= 0:
            raise ValueError("PRECIO_ENERGIA debe ser mayor que 0 (COP/kWh)")


class ConfiguracionOperativaCreate(BaseModel):
    # proyecto_id None → configuración global (aplica a cualquier proyecto).
    proyecto_id: Optional[int] = None
    tipo_parametro: TipoParametroConfigEnum
    valor_float: float
    unidad: str = Field(..., max_length=20)
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: bool = True

    @field_validator("valor_float")
    @classmethod
    def _valor_no_negativo(cls, v: float) -> float:
        if v < 0:
            raise ValueError("valor_float no puede ser negativo")
        return v

    @model_validator(mode="after")
    def _valor_en_rango(self) -> "ConfiguracionOperativaCreate":
        validar_rango_por_tipo(self.tipo_parametro, self.valor_float)
        return self


class ConfiguracionOperativaUpdate(BaseModel):
    """Actualización parcial: solo se aplican los campos presentes.

    No incluye `tipo_parametro` (el tipo de un parámetro no se cambia in-place). La
    validación de rango por tipo se hace en el endpoint contra el tipo de la fila
    existente, ya que aquí no tenemos ese contexto.
    """
    valor_float: Optional[float] = None
    unidad: Optional[str] = Field(default=None, max_length=20)
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
