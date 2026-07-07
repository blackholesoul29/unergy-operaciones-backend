"""Schemas Pydantic de la automatización de liquidación XM (``LiquidacionXMIngesta``).

Se mantienen separados de los serializadores manuales de ``app/api/v1/liquidaciones.py``
porque cubren la salida del proceso automático disparado al aprobar un informe.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LiquidacionXMIngestaBase(BaseModel):
    informe_id: int
    proyecto_id: int
    fecha: date
    energia_generada_kwh: float
    hora: Optional[int] = None
    ppa_contrato_id: Optional[int] = None
    precio_bolsa_cop_kwh: Optional[float] = None
    valor_liquidado_cop: Optional[float] = None
    fuente_datos: str
    estado_proceso: str = "procesado"
    datos_adicionales: Optional[dict] = None


class LiquidacionXMIngestaCreate(LiquidacionXMIngestaBase):
    pass


class LiquidacionXMIngesta(LiquidacionXMIngestaBase):
    """Schema de lectura (from ORM)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class LiquidacionIngestaResumen(BaseModel):
    """Resumen agregado que devuelve el orquestador tras una corrida."""
    informe_id: int
    liquidacion_status: str
    proyectos: list[int] = []
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    filas_creadas: int = 0
    energia_total_kwh: float = 0.0
    valor_liquidado_total_cop: float = 0.0
    dias_sin_precio: int = 0
    error: Optional[str] = None
