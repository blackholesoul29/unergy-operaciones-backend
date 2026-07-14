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


class AlertaDeficitPPAOut(BaseModel):
    """Alerta de déficit de cumplimiento PPA (GET /alertas/cumplimiento-ppa)."""
    tipo: str
    severidad: str
    contrato_ppa_id: int
    contrato_nombre: str | None = None
    comprador_nombre: str | None = None
    anio: int
    mes: int
    gen_total_mwh: float
    compromiso_mwh: float
    cobertura_pct: float
    deficit_mwh: float
    impacto_estimado_cop: float | None = None
    precio_bolsa_promedio: float | None = None  # COP/kWh (fuente XM)
    # Con qué precio se valoró el déficit: el frontend muestra el número y de
    # dónde salió ('BOLSA' o 'PENALIDAD_CONTRACTUAL').
    precio_aplicado_mwh: float | None = None  # COP/MWh
    fuente_precio: str | None = None
    mensaje: str


class PeriodoOut(BaseModel):
    anio: int
    mes: int


class AlertasCumplimientoPPAOut(BaseModel):
    fecha_consulta: str
    periodo: PeriodoOut
    umbral_pct: float
    total_alertas: int
    alertas: list[AlertaDeficitPPAOut]
