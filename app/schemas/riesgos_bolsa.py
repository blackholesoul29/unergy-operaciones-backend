"""Esquemas Pydantic del módulo Riesgos de Bolsa."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ── PrecioBolsa ─────────────────────────────────────────────────────────────

class PrecioBolsaBase(BaseModel):
    fecha_hora: datetime
    precio_cop_mwh: Decimal


class PrecioBolsaCreate(PrecioBolsaBase):
    pass


class PrecioBolsaOut(PrecioBolsaBase):
    id: int
    model_config = {"from_attributes": True}


# ── Ingesta ─────────────────────────────────────────────────────────────────

class IngestPrecioBolsaRequest(BaseModel):
    file_path: str = Field(..., description="Ruta del archivo XM de precio de bolsa")
    convertir_kwh_a_mwh: bool = Field(
        True, description="XM publica en COP/kWh; True multiplica x1000 a COP/MWh"
    )


class IngestResult(BaseModel):
    insertados: int
    actualizados: int
    total_filas: int


# ── Exposición ──────────────────────────────────────────────────────────────

class ExposureResult(BaseModel):
    fecha: date | None = None
    planta_id: int | None = None
    generacion_mwh: float | None = Field(None, description="Generación real del día (MWh). None si aún no hay dato cargado.")
    ppa_obligacion_mwh: float | None = Field(None, description="Obligación PPA prorrateada del día (MWh). 0 si el contrato no exige mínimo ese mes.")
    precio_cop_mwh: float | None = Field(None, description="Precio de bolsa promedio del día (COP/MWh). None si no hay precio.")
    exposicion_cop: float | None = Field(None, description="(generación − obligación) × precio (COP). None si falta generación o precio: NO se fabrica con generación=0.")
    datos_completos: bool = Field(True, description="True sólo si el día tiene precio Y generación real. Los días incompletos NO entran en los indicadores de riesgo.")


class RiskIndicators(BaseModel):
    n: int = Field(..., description="Nº de días COMPLETOS (con exposición real) sobre los que se calculan los indicadores.")
    exposicion_total_cop: float
    exposicion_media_cop: float | None = None
    exposicion_std_cop: float | None = None
    exposicion_max_cop: float | None = None
    exposicion_min_cop: float | None = None
    var_95_cop: float | None = Field(None, description="VaR 95% = percentil 5 de la exposición firmada (COP). Valor bajo/negativo = mayor pérdida esperada con 95% de confianza.")


class HistoricalExposureOut(BaseModel):
    puntos: list[ExposureResult]
    indicadores: RiskIndicators


class RiskIndicatorsOutput(RiskIndicators):
    start_dt: date
    end_dt: date
    planta_id: int | None = None


# ── Proyección de escenarios ────────────────────────────────────────────────

class ScenarioPoint(BaseModel):
    fecha: date
    precio_cop_mwh: float
    generacion_mwh: float | None = 0.0
    ppa_obligacion_mwh: float | None = 0.0


class ProjectedExposureInput(BaseModel):
    planta_id: int | None = None
    puntos: list[ScenarioPoint]


class ProjectedExposureOut(BaseModel):
    puntos: list[ExposureResult]
    indicadores: RiskIndicators
