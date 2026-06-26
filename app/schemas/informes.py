"""
Schemas de la generación automática de informes.

Cubren el endpoint ``POST /informes/generar`` (disparar la generación) y las
respuestas de borrador. La persistencia reutiliza ``informes_guardados`` /
``InformeGuardado`` (mismo flujo editorial que los informes hechos a mano).
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

REPORT_TYPES = ("op", "fmo", "port")


class ReportCreate(BaseModel):
    """Solicitud de generación de un informe.

    - ``op``/``fmo``: ``sub_project`` es el proyecto (sub_project o nombre).
    - ``port``: ``sub_project`` es el nombre (o id) del portafolio.
    """

    tipo: str = Field(..., description="op | fmo | port")
    sub_project: str = Field(..., min_length=1, description="proyecto o portafolio")
    periodo_desde: date
    periodo_hasta: date

    @model_validator(mode="after")
    def _validate(self) -> "ReportCreate":
        if self.tipo not in REPORT_TYPES:
            raise ValueError(f"tipo inválido: '{self.tipo}'. Use uno de {REPORT_TYPES}.")
        if self.periodo_hasta < self.periodo_desde:
            raise ValueError("periodo_hasta no puede ser anterior a periodo_desde")
        return self


class ReportResponse(BaseModel):
    """Respuesta resumida tras generar/guardar un borrador."""

    id: int
    tipo: str
    sub_project: str
    estado: str
    periodo_desde: str
    periodo_hasta: str
    periodo_display: str | None = None
    proyecto_nombre: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class ReportDraftResponse(ReportResponse):
    """Respuesta completa con el contenido del borrador."""

    html_content: str
    charts_data: dict | None = None
