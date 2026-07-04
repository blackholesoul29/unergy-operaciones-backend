"""Schemas Pydantic del módulo de Impacto de Mantenimiento."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MantenimientoImpactoCreate(BaseModel):
    proyecto_id: int
    start_time: datetime
    end_time: datetime
    maintenance_type: str = "scheduled"
    falla_id: Optional[int] = None
    # Opcionales: si no se envían, el ImpactCalculator los deduce de la
    # generación histórica (kwh_p90 esperado / kwh_real) del período.
    expected_generation_kwh: Optional[float] = None
    actual_generation_kwh: Optional[float] = None


class MantenimientoImpactoUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    maintenance_type: Optional[str] = None
    falla_id: Optional[int] = None
    expected_generation_kwh: Optional[float] = None
    actual_generation_kwh: Optional[float] = None


class MantenimientoImpactoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proyecto_id: int
    proyecto_nombre: Optional[str] = None
    falla_id: Optional[int] = None
    maintenance_type: str
    start_time: datetime
    end_time: datetime
    duration_hours: Optional[float] = None
    expected_generation_kwh: Optional[float] = None
    actual_generation_kwh: Optional[float] = None
    # Calculados por el servicio, de solo lectura en la respuesta.
    lost_energy_kwh: Optional[float] = None
    financial_impact_cop: Optional[float] = None
    ppa_penalty_risk_flag: bool = False
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
