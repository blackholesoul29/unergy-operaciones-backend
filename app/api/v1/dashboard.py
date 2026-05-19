"""Dashboard KPI endpoint — single call for all dashboard metrics."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models import (
    Proyecto, Cliente, Falla, FallaCatEstado,
    Liquidacion, GeneracionDiaria, PPAContrato,
)
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("dashboard")

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/kpis")
def dashboard_kpis(db: Session = Depends(get_db), _=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    proyectos_total = db.query(func.count(Proyecto.id)).scalar() or 0
    proyectos_operacion = db.query(func.count(Proyecto.id)).filter(
        Proyecto.estado == "en_operacion"
    ).scalar() or 0

    clientes_total = db.query(func.count(Cliente.id)).scalar() or 0

    fallas_abiertas = db.query(func.count(Falla.id)).join(
        FallaCatEstado, Falla.estado_id == FallaCatEstado.id
    ).filter(~FallaCatEstado.es_estado_final).scalar() or 0

    liquidaciones_mes = db.query(func.count(Liquidacion.id)).filter(
        Liquidacion.created_at >= month_start
    ).scalar() or 0

    kwh_mes = db.query(func.sum(GeneracionDiaria.kwh_real)).filter(
        GeneracionDiaria.fecha >= month_start.date()
    ).scalar()
    mwh_mes = round(float(kwh_mes) / 1000, 1) if kwh_mes else 0

    ppa_activos = db.query(func.count(PPAContrato.id)).scalar() or 0

    precio_bolsa = None
    try:
        row = db.execute(text(
            "SELECT precio_promedio FROM precios_bolsa_diario ORDER BY fecha DESC LIMIT 1"
        )).first()
        if row:
            precio_bolsa = round(float(row[0]), 1)
    except Exception:
        pass

    mgs_activas = 0
    try:
        row = db.execute(text(
            "SELECT COUNT(*) FROM alarmas_monitoreo WHERE resolved_at IS NULL"
        )).first()
        if row:
            mgs_activas = row[0]
    except Exception:
        pass

    fleet_power_kw = None
    fleet_online = None
    try:
        client = SoleniumClient()
        if client.enabled:
            summary = client.get_project_summary()
            fleet_power_kw = round(sum(s.get("power_kw") or 0 for s in summary), 1)
            fleet_online = sum(1 for s in summary if (s.get("power_kw") or 0) > 0)
    except Exception:
        logger.debug("Solenium fleet summary unavailable", exc_info=True)

    return {
        "proyectos_total": proyectos_total,
        "proyectos_operacion": proyectos_operacion,
        "clientes_total": clientes_total,
        "fallas_abiertas": fallas_abiertas,
        "liquidaciones_mes": liquidaciones_mes,
        "mwh_mes": mwh_mes,
        "ppa_activos": ppa_activos,
        "precio_bolsa_cop_kwh": precio_bolsa,
        "alarmas_mgs": mgs_activas,
        "fleet_power_kw": fleet_power_kw,
        "fleet_online": fleet_online,
    }
