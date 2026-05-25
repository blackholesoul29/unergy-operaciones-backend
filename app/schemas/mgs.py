from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class AlarmOut(BaseModel):
    id: int
    proyecto_nombre: str
    severity: str
    alarm_type: str
    details: str
    source_data: dict | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class PlantOut(BaseModel):
    name: str
    status: str
    kwh: int
    inverter_obs: str | None = None


class StatusCountsOut(BaseModel):
    OK: int = 0
    WARNING: int = 0
    NO_DATA: int = 0
    ERROR: int = 0


class SummaryOut(BaseModel):
    date: str | None = None
    time: str | None = None
    status_counts: StatusCountsOut | None = None
    projects: list[PlantOut] = []
    total_projects: int = 0
    daily_critical: int = 0
    daily_warning: int = 0
    daily_recoveries: int = 0


class MGSStatusOut(BaseModel):
    last_poll: str | None = None
    summary: SummaryOut | None = None
    active_alarms: list[dict] = []
    inverter_observations: dict[str, str] = {}
