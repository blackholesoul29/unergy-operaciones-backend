"""Schemas Pydantic para las alertas persistentes (tabla `alertas`)."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AlertaBase(BaseModel):
    ppa_id: int
    project_id: Optional[int] = None
    alert_type: str
    description: Optional[str] = None
    due_date: date
    days_to_expiration: int
    status: str = "new"


class AlertaCreate(AlertaBase):
    pass


class Alerta(AlertaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger_date: date
    created_at: datetime
    updated_at: datetime
