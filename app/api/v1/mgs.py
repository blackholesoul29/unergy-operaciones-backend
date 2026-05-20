"""MGS Alarms — real-time solar plant monitoring endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.services.mgs import scheduler

router = APIRouter(prefix="/mgs", tags=["MGS Monitoreo"])


@router.get("/status")
def mgs_status(_=Depends(get_current_user)):
    return scheduler.get_status()


@router.get("/plants")
def mgs_plants(_=Depends(get_current_user)):
    return scheduler.get_plants()


@router.get("/plants/{name}")
def mgs_plant_detail(name: str, _=Depends(get_current_user)):
    plants = scheduler.get_plants()
    for p in plants:
        if p["name"] == name:
            return p
    return {"error": "Proyecto no encontrado"}


@router.get("/alarms")
def mgs_alarms(
    severity: str | None = Query(None),
    alarm_type: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = """
        SELECT id, proyecto_nombre, severity, alarm_type, details,
               source_data, resolved_at, created_at
        FROM alarmas_monitoreo
        WHERE resolved_at IS NULL
    """
    params: dict = {}
    if severity:
        q += " AND severity = :severity"
        params["severity"] = severity
    if alarm_type:
        q += " AND alarm_type = :alarm_type"
        params["alarm_type"] = alarm_type
    q += " ORDER BY created_at DESC LIMIT 100"

    rows = db.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/alarms/history")
def mgs_alarms_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    offset = (page - 1) * page_size
    rows = db.execute(text("""
        SELECT id, proyecto_nombre, severity, alarm_type, details,
               resolved_at, created_at
        FROM alarmas_monitoreo
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset}).mappings().all()

    total = db.execute(text("SELECT COUNT(*) FROM alarmas_monitoreo")).scalar()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/alarms/{alarm_id}/resolve")
def mgs_resolve_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    result = db.execute(
        text("""
            UPDATE alarmas_monitoreo
            SET resolved_at = NOW()
            WHERE id = :id AND resolved_at IS NULL
            RETURNING id, proyecto_nombre, alarm_type
        """),
        {"id": alarm_id},
    ).mappings().first()
    db.commit()
    if not result:
        return {"error": "Alarma no encontrada o ya resuelta"}
    return {"status": "resolved", "alarm": dict(result)}


@router.patch("/alarms/resolve-all")
def mgs_resolve_all(
    severity: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = "UPDATE alarmas_monitoreo SET resolved_at = NOW() WHERE resolved_at IS NULL"
    params: dict = {}
    if severity:
        q += " AND severity = :severity"
        params["severity"] = severity
    result = db.execute(text(q), params)
    db.commit()
    return {"status": "resolved", "count": result.rowcount}


@router.post("/poll")
def mgs_force_poll(_=Depends(get_current_user)):
    started = scheduler.poll_once_async()
    if started:
        return {"status": "poll_started"}
    return {"status": "poll_already_running"}
