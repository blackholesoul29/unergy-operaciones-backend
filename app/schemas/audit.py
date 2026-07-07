"""Schemas de la API de monitoreo de auditoría."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


class AuditAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_name: str
    entity_type: str
    entity_id: str
    trigger_reason: str
    severity: str
    status: str
    usuario_nombre: Optional[str] = None
    detalle: Optional[dict[str, Any]] = None
    notificado: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime


class AuditRuleCreate(BaseModel):
    name: str
    entity_type: Literal["liquidacion", "ppa", "generacion"]
    condition_json: Optional[dict[str, Any]] = None
    active: bool = True


class AuditRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    entity_type: str
    condition_json: Optional[dict[str, Any]] = None
    active: bool
    created_at: datetime


class AuditAckRequest(BaseModel):
    alert_id: int
