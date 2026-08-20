"""Schemas del pipeline mensual de cumplimiento PPA.

El pipeline cruza contratos (AsicSolicitud/PPA), lecturas de frontera y
generación diaria para calcular el snapshot de cumplimiento del mes y derivar
los datos XM de liquidación. Estos schemas describen la petición y la respuesta
del endpoint que lo dispara.
"""
from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    anio: int = Field(..., ge=2020, le=2050)
    mes: int = Field(..., ge=1, le=12)


class PipelineRunResponse(BaseModel):
    status: str
    message: str
    anio: int
    mes: int
    cumplimiento_recs_processed: int = 0
    liquidaciones_recs_created: int = 0
