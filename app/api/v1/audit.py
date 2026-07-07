"""API de monitoreo de auditoría — alertas y reglas configurables."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.audit_alert import (
    STATUS_ACKNOWLEDGED,
    AuditAlert,
    AuditRule,
)
from app.models.usuarios import Usuario
from app.schemas.audit import (
    AuditAckRequest,
    AuditAlertOut,
    AuditRuleCreate,
    AuditRuleOut,
)

router = APIRouter(prefix="/audit", tags=["Auditoría"])

_MANAGE_ROLES = {"admin", "operaciones"}


def _require_manage(current: Usuario) -> None:
    if current.rol.value not in _MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="Se requiere rol admin u operaciones")


@router.get("/alerts", response_model=list[AuditAlertOut])
def list_alerts(
    entity_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Lista alertas de auditoría con filtros opcionales (paginado)."""
    q = db.query(AuditAlert)
    if entity_type:
        q = q.filter(AuditAlert.entity_type == entity_type)
    if severity:
        q = q.filter(AuditAlert.severity == severity)
    if status:
        q = q.filter(AuditAlert.status == status)
    return (
        q.order_by(AuditAlert.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )


@router.post("/rules", response_model=AuditRuleOut)
def upsert_rule(
    data: AuditRuleCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Crea o actualiza una regla de auditoría (por nombre + tipo de entidad)."""
    _require_manage(current)
    rule = (
        db.query(AuditRule)
        .filter(AuditRule.name == data.name, AuditRule.entity_type == data.entity_type)
        .first()
    )
    if rule is None:
        rule = AuditRule(
            name=data.name,
            entity_type=data.entity_type,
            condition_json=data.condition_json,
            active=data.active,
        )
        db.add(rule)
    else:
        rule.condition_json = data.condition_json
        rule.active = data.active
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/rules", response_model=list[AuditRuleOut])
def list_rules(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Lista todas las reglas de auditoría configuradas."""
    return db.query(AuditRule).order_by(AuditRule.id.desc()).all()


@router.post("/ack", response_model=AuditAlertOut)
def acknowledge_alert(
    data: AuditAckRequest,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Marca una alerta como resuelta (acknowledged)."""
    _require_manage(current)
    alert = db.query(AuditAlert).filter(AuditAlert.id == data.alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    alert.status = STATUS_ACKNOWLEDGED
    alert.acknowledged_by = current.nombre
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert
