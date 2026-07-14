"""Dashboard KPI endpoint — single call for all dashboard metrics."""
import logging
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models import (
    Proyecto, Cliente, Falla, FallaCatEstado, FallaCatPrioridad,
    Liquidacion, GeneracionDiaria, PPAContrato, PPACompromisoEnergia,
    Garantia, CumplimientoMensual,
)
from app.models.garantias import EstadoGarantiaEnum
from app.services.garantias_saldo import saldos_vivos
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("dashboard")

_fleet_cache: dict = {"data": None, "ts": 0}
_FLEET_TTL = 180  # 3 minutes

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
    mgs_criticas = 0
    try:
        row = db.execute(text(
            "SELECT COUNT(*) FROM alarmas_monitoreo WHERE resolved_at IS NULL"
        )).first()
        if row:
            mgs_activas = row[0]
        row = db.execute(text(
            "SELECT COUNT(*) FROM alarmas_monitoreo WHERE resolved_at IS NULL AND severity = 'CRITICAL'"
        )).first()
        if row:
            mgs_criticas = row[0]
    except Exception:
        pass

    fleet_power_kw = None
    fleet_online = None
    fleet_total = None
    now = time.monotonic()
    if _fleet_cache["data"] and (now - _fleet_cache["ts"]) < _FLEET_TTL:
        fleet_power_kw, fleet_online, fleet_total = _fleet_cache["data"]
    else:
        try:
            client = SoleniumClient()
            if client.enabled:
                summary = client.get_project_summary()
                fleet_power_kw = round(sum(s.get("power_kw") or 0 for s in summary), 1)
                fleet_online = sum(1 for s in summary if (s.get("power_kw") or 0) > 0)
                fleet_total = len(summary)
                _fleet_cache["data"] = (fleet_power_kw, fleet_online, fleet_total)
                _fleet_cache["ts"] = now
        except Exception:
            logger.debug("Solenium fleet summary unavailable", exc_info=True)

    # Fallas by priority (for severity breakdown)
    fallas_por_prioridad = {}
    try:
        rows = (
            db.query(FallaCatPrioridad.codigo, func.count(Falla.id))
            .join(FallaCatPrioridad, Falla.prioridad_id == FallaCatPrioridad.id)
            .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
            .filter(~FallaCatEstado.es_estado_final)
            .group_by(FallaCatPrioridad.codigo)
            .all()
        )
        fallas_por_prioridad = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    # Critical fallas older than 7 days (stale critical issues)
    fallas_criticas_antiguas = 0
    try:
        cutoff = date.today() - timedelta(days=7)
        fallas_criticas_antiguas = (
            db.query(func.count(Falla.id))
            .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
            .join(FallaCatPrioridad, Falla.prioridad_id == FallaCatPrioridad.id)
            .filter(
                ~FallaCatEstado.es_estado_final,
                FallaCatPrioridad.codigo == "critica",
                Falla.fecha_identificacion <= cutoff,
            )
            .scalar() or 0
        )
    except Exception:
        pass

    # PPA contracts with commitments this month (lightweight DB-only check)
    today = date.today()
    ppa_con_compromisos = 0
    try:
        ppa_con_compromisos = (
            db.query(func.count(func.distinct(PPACompromisoEnergia.contrato_id)))
            .filter(
                PPACompromisoEnergia.año == today.year,
                PPACompromisoEnergia.mes == today.month,
            )
            .scalar() or 0
        )
    except Exception:
        pass

    # Garantías: expiring within 30 days + total balance
    garantias_vigentes = 0
    garantias_por_vencer = 0
    garantias_valor_total = 0
    try:
        threshold = today + timedelta(days=30)
        garantias_vigentes = (
            db.query(func.count(Garantia.id))
            .filter(Garantia.estado == EstadoGarantiaEnum.vigente)
            .scalar() or 0
        )
        garantias_por_vencer = (
            db.query(func.count(Garantia.id))
            .filter(
                Garantia.estado == EstadoGarantiaEnum.vigente,
                Garantia.fecha_vencimiento.isnot(None),
                Garantia.fecha_vencimiento <= threshold,
            )
            .scalar() or 0
        )
        # Saldo VIVO, no el constituido: `valor_cop` nunca baja con los cobros de XM, así
        # que sumarlo aquí sobreestimaba la cobertura en el primer KPI que ve operaciones.
        vigentes = (
            db.query(Garantia)
            .filter(Garantia.estado == EstadoGarantiaEnum.vigente)
            .all()
        )
        saldos = saldos_vivos(db, vigentes)
        garantias_valor_total = round(sum(saldos[g.id] for g in vigentes), 0) if vigentes else 0
    except Exception:
        pass

    # Liquidaciones: projects pending settlement this month
    liquidaciones_pendientes = 0
    try:
        liq_done = (
            db.query(Liquidacion.proyecto_id)
            .filter(
                Liquidacion.periodo == today.replace(day=1),
                Liquidacion.deleted_at.is_(None),
            )
            .subquery()
        )
        liquidaciones_pendientes = (
            db.query(func.count(Proyecto.id))
            .filter(
                Proyecto.estado == "en_operacion",
                ~Proyecto.id.in_(db.query(liq_done.c.proyecto_id)),
            )
            .scalar() or 0
        )
    except Exception:
        pass

    # Generation data freshness (last Solenium sync)
    gen_last_date = None
    gen_projects_with_data = 0
    try:
        row = db.execute(text(
            "SELECT MAX(fecha) FROM generacion_diaria WHERE fuente = 'solenium'"
        )).first()
        if row and row[0]:
            gen_last_date = row[0].isoformat()
        count_row = db.execute(text(
            "SELECT COUNT(DISTINCT proyecto_id) FROM generacion_diaria "
            "WHERE fuente = 'solenium' AND fecha >= CURRENT_DATE - INTERVAL '7 days'"
        )).first()
        if count_row:
            gen_projects_with_data = count_row[0]
    except Exception:
        pass

    # ── PPA compliance snapshot (current month from cumplimiento_mensual) ────
    cumplimiento_ppa = {
        "contratos_con_deficit": 0,
        "contratos_cumplidos": 0,
        "exposicion_bolsa_cop": 0,
        "cobertura_pct": None,
    }
    try:
        cm_rows = (
            db.query(CumplimientoMensual)
            .filter(
                CumplimientoMensual.anio == today.year,
                CumplimientoMensual.mes == today.month,
            )
            .all()
        )
        if cm_rows:
            total_gen = 0.0
            total_compromiso = 0.0
            total_exposicion = 0.0
            for cm in cm_rows:
                gen = float(cm.gen_total_mwh) if cm.gen_total_mwh is not None else 0
                comp = float(cm.compromiso_mwh) if cm.compromiso_mwh is not None else None
                compras_cop = float(cm.compras_bolsa_cop) if cm.compras_bolsa_cop is not None else 0

                if comp is not None:
                    total_compromiso += comp
                    total_gen += gen
                    if gen < comp:
                        cumplimiento_ppa["contratos_con_deficit"] += 1
                    else:
                        cumplimiento_ppa["contratos_cumplidos"] += 1
                    total_exposicion += compras_cop

            cumplimiento_ppa["exposicion_bolsa_cop"] = round(total_exposicion, 0)
            if total_compromiso > 0:
                cumplimiento_ppa["cobertura_pct"] = round(
                    (total_gen / total_compromiso) * 100, 1,
                )
    except Exception:
        logger.debug("cumplimiento_ppa metrics failed", exc_info=True)

    return {
        "proyectos_total": proyectos_total,
        "proyectos_operacion": proyectos_operacion,
        "clientes_total": clientes_total,
        "fallas_abiertas": fallas_abiertas,
        "fallas_por_prioridad": fallas_por_prioridad,
        "fallas_criticas_antiguas": fallas_criticas_antiguas,
        "liquidaciones_mes": liquidaciones_mes,
        "mwh_mes": mwh_mes,
        "ppa_activos": ppa_activos,
        "ppa_con_compromisos": ppa_con_compromisos,
        "precio_bolsa_cop_kwh": precio_bolsa,
        "alarmas_mgs": mgs_activas,
        "alarmas_mgs_criticas": mgs_criticas,
        "fleet_power_kw": fleet_power_kw,
        "fleet_online": fleet_online,
        "fleet_total": fleet_total,
        "garantias_vigentes": garantias_vigentes,
        "garantias_por_vencer": garantias_por_vencer,
        "garantias_valor_total_cop": garantias_valor_total,
        "gen_solenium_last_date": gen_last_date,
        "gen_solenium_projects": gen_projects_with_data,
        "liquidaciones_pendientes": liquidaciones_pendientes,
        "cumplimiento_ppa": cumplimiento_ppa,
    }
