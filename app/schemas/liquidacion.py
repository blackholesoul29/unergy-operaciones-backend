"""Schemas del motor de liquidación XM (tabla `liquidacion_xm_calculos`).

Validan la entrada del trigger y la salida de consulta del motor. Los rangos
de valores se validan con Pydantic; los tipos coinciden con el modelo SQL
(`LiquidacionXMCalculo`).
"""
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

ESTADOS_VALIDOS = ("pendiente", "calculado", "auditado")


class LiquidacionTriggerRequest(BaseModel):
    """Entrada de POST /trigger-calculation: dispara el cálculo de un proyecto."""
    proyecto_id: int = Field(..., gt=0)
    mes: int = Field(..., ge=1, le=12)
    anio: int = Field(..., ge=2020, le=2050)


class LiquidacionCreate(BaseModel):
    """Alta/actualización manual de un cálculo de liquidación (poco común: lo
    normal es que lo genere el motor). Se valida como el modelo SQL."""
    proyecto_id: int = Field(..., gt=0)
    periodo: date
    generacion_real: float = Field(..., ge=0)
    compromiso_ppa: float = Field(..., ge=0)
    precio_xm_promedio: float = Field(..., ge=0)
    diferencia_mwh: float
    valor_liquidacion: float
    estado: str = "pendiente"

    @field_validator("estado")
    @classmethod
    def _estado_valido(cls, v: str) -> str:
        if v not in ESTADOS_VALIDOS:
            raise ValueError(f"estado debe ser uno de {ESTADOS_VALIDOS}")
        return v


class LiquidacionResponse(BaseModel):
    """Salida de consulta del motor."""
    id: int
    proyecto_id: int
    periodo: date
    generacion_real: float
    compromiso_ppa: float
    precio_xm_promedio: float
    diferencia_mwh: float
    valor_liquidacion: float
    estado: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
