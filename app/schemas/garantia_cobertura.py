"""Schemas Pydantic para el monitoreo de cobertura de garantías."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NIVELES_ALERTA = ("VERDE", "AMARILLO", "ROJO")


class GarantiaCoberturaHistoricoBase(BaseModel):
    garantia_id: int
    valor_requerido: float
    valor_actual_garantia: float
    cobertura_porcentaje: Optional[float] = None
    nivel_alerta: str
    detalles_calculo: Optional[dict[str, Any]] = None

    @field_validator("nivel_alerta")
    @classmethod
    def nivel_valido(cls, v: str) -> str:
        if v not in NIVELES_ALERTA:
            raise ValueError(f"nivel_alerta inválido: {v}")
        return v


class GarantiaCoberturaHistoricoCreate(GarantiaCoberturaHistoricoBase):
    pass


class GarantiaCoberturaHistorico(GarantiaCoberturaHistoricoBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fecha_verificacion: datetime


class GarantiaMonitoreoConfig(BaseModel):
    """Configuración editable del monitoreo automático de una garantía."""
    monitoreo_cobertura_activo: Optional[bool] = None
    tipo_calculo_cobertura: Optional[str] = None
    umbral_alerta_amarilla: Optional[float] = None
    umbral_alerta_roja: Optional[float] = None

    @field_validator("umbral_alerta_amarilla", "umbral_alerta_roja")
    @classmethod
    def umbral_en_rango(cls, v):
        if v is not None and not (0 < v <= 1):
            raise ValueError("los umbrales deben estar en el rango (0, 1]")
        return v

    @model_validator(mode="after")
    def roja_no_supera_amarilla(self):
        r, a = self.umbral_alerta_roja, self.umbral_alerta_amarilla
        if r is not None and a is not None and r > a:
            raise ValueError(
                "el umbral de alerta roja debe ser menor o igual que el de amarilla "
                "(la roja es el piso más estricto de cobertura)"
            )
        return self
