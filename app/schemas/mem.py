"""Schemas Pydantic para las respuestas del MEM/XM.

Validan lo que ``app/services/mem_ingestion_service.py`` recibe de la API REST
del mercado (precio de bolsa y asignaciones). El servicio normaliza la
respuesta cruda de XM a estas estructuras antes de devolverlas, de modo que el
orquestador dependa de un contrato estable y no del formato exacto del proveedor.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class PrecioBolsaDia(BaseModel):
    """Precio de bolsa nacional para una fecha, expresado en COP/kWh.

    XM publica el precio en COP/kWh (a veces COP/MWh según el reporte); el
    servicio se encarga de dejar SIEMPRE COP/kWh aquí para que el cálculo del
    orquestador sea directo (energía_kwh * precio = COP).
    """
    model_config = ConfigDict(from_attributes=True)

    fecha: date
    precio_cop_kwh: float

    @field_validator("precio_cop_kwh")
    @classmethod
    def _no_negativo(cls, v: float) -> float:
        if v is None:
            raise ValueError("precio_cop_kwh no puede ser None")
        if v < 0:
            raise ValueError(f"precio_cop_kwh no puede ser negativo: {v}")
        return v


class AsignacionMEM(BaseModel):
    """Asignación/energía liquidada por el MEM para un agente en una fecha."""
    model_config = ConfigDict(from_attributes=True)

    fecha: date
    agente: str
    energia_kwh: float
    codigo_frontera: Optional[str] = None


class RespuestaPreciosBolsa(BaseModel):
    """Envoltorio de la respuesta de precios de bolsa."""
    items: list[PrecioBolsaDia] = []


class RespuestaAsignaciones(BaseModel):
    """Envoltorio de la respuesta de asignaciones."""
    items: list[AsignacionMEM] = []
