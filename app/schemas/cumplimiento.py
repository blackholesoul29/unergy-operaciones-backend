"""Schemas for cumplimiento mensual PPA."""
from datetime import datetime
from pydantic import BaseModel, Field


class CumplimientoMensualCreate(BaseModel):
    contrato_ppa_id: int
    proyecto_id: int | None = None
    anio: int = Field(..., ge=2020, le=2050)
    mes: int = Field(..., ge=1, le=12)
    gen_total_mwh: float | None = None
    compromiso_mwh: float | None = None
    compras_bolsa_mwh: float | None = None
    excedentes_bolsa_mwh: float | None = None
    precio_bolsa_promedio: float | None = None
    compras_bolsa_cop: float | None = None
    excedentes_bolsa_cop: float | None = None
    tarifa_ppa_cop_mwh: float | None = None
    valoracion_contrato_cop: float | None = None


class CumplimientoMensualOut(BaseModel):
    id: int
    contrato_ppa_id: int
    proyecto_id: int | None = None
    anio: int
    mes: int
    gen_total_mwh: float | None = None
    compromiso_mwh: float | None = None
    compras_bolsa_mwh: float | None = None
    excedentes_bolsa_mwh: float | None = None
    precio_bolsa_promedio: float | None = None
    compras_bolsa_cop: float | None = None
    excedentes_bolsa_cop: float | None = None
    estado: str
    tarifa_ppa_cop_mwh: float | None = None
    valoracion_contrato_cop: float | None = None
    liquidacion_id: int | None = None
    contrato_nombre: str | None = None
    comprador_nombre: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class CerrarPeriodoRequest(BaseModel):
    anio: int = Field(..., ge=2020, le=2050)
    mes: int = Field(..., ge=1, le=12)


class CerrarPeriodoResponse(BaseModel):
    anio: int
    mes: int
    contratos_procesados: int
    contratos_con_deficit: int
    contratos_cumplidos: int
    registros: list[CumplimientoMensualOut]


class FacturarRequest(BaseModel):
    liquidacion_id: int | None = None


# ── KPI Cumplimiento PPA (comprometido vs. generado) ─────────────────────────


class PPACumplimientoResponse(BaseModel):
    """KPI base de cumplimiento PPA de un proyecto: comprometido vs. generado."""
    project_id: int
    nombre: str | None = None
    target_mwh: float | None = None
    actual_mwh: float
    delta_mwh: float | None = None
    compliance_pct: float | None = None
    has_ppa: bool


class ProjectCumplimientoDetail(PPACumplimientoResponse):
    """Detalle de cumplimiento PPA para un proyecto específico en un período."""
    year: int
    month: int


class FleetCumplimientoSummary(BaseModel):
    """Cumplimiento PPA agregado a nivel flota más el desglose por proyecto."""
    year: int
    month: int
    total_target_mwh: float
    total_actual_mwh: float
    total_delta_mwh: float
    fleet_compliance_pct: float | None = None
    n_proyectos: int
    n_con_ppa: int
    proyectos: list[PPACumplimientoResponse]
