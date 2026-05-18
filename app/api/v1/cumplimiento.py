"""
Módulo de cumplimiento contractual de energía.

Endpoint principal: GET /cumplimiento/ppa/{contrato_id}?year=&month=
Consulta la generación real desde la API de Unergy para las plantas
asignadas al contrato vía GESCON (asic_solicitudes) y la cruza con
los compromisos de energía (min/max MWh) del contrato PPA.
"""

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.asic import AsicSolicitud, TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.models.contratos import PPAContrato, PPACompromisoEnergia, PPATarifa

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cumplimiento", tags=["Cumplimiento"])


# ── Unergy API ────────────────────────────────────────────────────────────────

def _unergy_token() -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/",
            json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD},
            headers={"User-Agent": "PostmanRuntime/7.50.0"},
        )
        resp.raise_for_status()
        return resp.json()["access"]


def _fetch_month(token: str, sub_project: str, year: int, month: int) -> dict:
    """
    Consulta la generación acumulada de un mes para un sub_project.
    Devuelve MWh del mes = (último acumulado – primero) / 1000.
    Colombia = UTC-5: agrega 5h para obtener el timestamp UTC correcto.
    """
    tz_offset = timedelta(hours=5)
    last_day = calendar.monthrange(year, month)[1]
    start_utc = datetime(year, month, 1, 0, 0, 0) + tz_offset
    end_utc = datetime(year, month, last_day, 23, 59, 59) + tz_offset

    try:
        with httpx.Client(timeout=90) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation",
                params={
                    "time_stamp__gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "PostmanRuntime/7.50.0",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.warning("API error sub_project=%s %d-%02d: %s", sub_project, year, month, exc)
        return {"mwh": None, "n_records": 0, "ultimo_dia": None}

    if not records:
        return {"mwh": None, "n_records": 0, "ultimo_dia": None}

    records_sorted = sorted(records, key=lambda r: r.get("time_stamp", ""))
    gen_first = records_sorted[0].get("generacion") or 0
    gen_last = records_sorted[-1].get("generacion") or 0
    diff_kwh = gen_last - gen_first
    if diff_kwh < 0:
        diff_kwh = gen_last  # contador reiniciado — usar solo el último

    ultimo_dia = None
    try:
        last_ts = records_sorted[-1].get("time_stamp", "")
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        col_dt = last_dt.replace(tzinfo=None) - timedelta(hours=5)  # UTC → Colombia
        ultimo_dia = col_dt.day
    except Exception:
        pass

    return {
        "mwh": round(diff_kwh / 1000, 3),
        "n_records": len(records),
        "ultimo_dia": ultimo_dia,
    }


# ── GESCON ────────────────────────────────────────────────────────────────────

def _resolve_gescon(db: Session, contrato_interno: str, year: int, month: int) -> list:
    """
    Devuelve los registros ASIC activos para el contrato en el mes dado.
    Aplica la regla GESCON: DISTINCT ON codigo_sic_contrato por fecha_solicitud
    más reciente, excluyendo terminaciones y desistimientos.
    """
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    records = (
        db.query(AsicSolicitud)
        .options(joinedload(AsicSolicitud.proyecto))
        .filter(
            AsicSolicitud.contrato_interno == contrato_interno,
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud != TipoSolicitudAsicEnum.desistimiento,
        )
        .order_by(AsicSolicitud.fecha_solicitud.desc().nullslast())
        .all()
    )

    # DISTINCT ON: solo la fila más reciente por codigo_sic_contrato
    seen: set = set()
    latest = []
    for r in records:
        key = r.codigo_sic_contrato or f"_id_{r.id}"
        if key not in seen:
            seen.add(key)
            latest.append(r)

    return [
        r for r in latest
        if r.tipo_solicitud != TipoSolicitudAsicEnum.terminacion
        and (r.fecha_fin is None or r.fecha_fin >= first_day)
        and (r.fecha_inicio is None or r.fecha_inicio <= last_day)
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/ppa")
def list_ppa(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Lista todos los contratos PPA para el selector."""
    rows = (
        db.query(PPAContrato)
        .order_by(PPAContrato.nombre_interno.nullslast(), PPAContrato.id)
        .all()
    )
    return [
        {
            "id": r.id,
            "nombre_interno": r.nombre_interno,
            "numero_codigo_contrato": r.numero_codigo_contrato,
            "comprador_nombre": r.comprador_nombre,
            "fecha_inicio": r.fecha_inicio.isoformat() if r.fecha_inicio else None,
            "fecha_fin": r.fecha_fin.isoformat() if r.fecha_fin else None,
        }
        for r in rows
    ]


@router.get("/ppa/{contrato_id}")
def get_cumplimiento(
    contrato_id: int,
    year: int = Query(..., ge=2020, le=2050),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Retorna el cumplimiento energético de un contrato PPA para un mes dado.
    Consulta la API de Unergy en paralelo (hasta 10 plantas simultáneas).
    """
    # ── 1. Contrato ───────────────────────────────────────────
    contrato = db.query(PPAContrato).filter(PPAContrato.id == contrato_id).first()
    if not contrato:
        raise HTTPException(404, "Contrato PPA no encontrado")

    # ── 2. Compromisos y tarifa ───────────────────────────────
    compromiso = (
        db.query(PPACompromisoEnergia)
        .filter(
            PPACompromisoEnergia.contrato_id == contrato_id,
            PPACompromisoEnergia.año == year,
            PPACompromisoEnergia.mes == month,
        )
        .first()
    )
    tarifa_row = (
        db.query(PPATarifa)
        .filter(
            PPATarifa.contrato_id == contrato_id,
            PPATarifa.año == year,
            PPATarifa.mes == month,
        )
        .first()
    )

    # ── 3. Período ────────────────────────────────────────────
    today = date.today()
    es_mes_actual = year == today.year and month == today.month
    total_dias = calendar.monthrange(year, month)[1]
    dia_actual = today.day if es_mes_actual else total_dias

    # ── 4. GESCON assignments ─────────────────────────────────
    if not contrato.numero_codigo_contrato:
        assignments = []
    else:
        assignments = _resolve_gescon(db, contrato.numero_codigo_contrato, year, month)

    # ── 5. Generación desde API Unergy (paralelo) ─────────────
    plantas_data = []
    sin_api_id: list[str] = []

    plants_with_id = []
    plants_without_id = []
    for asic in assignments:
        proyecto = asic.proyecto
        nombre = proyecto.nombre_comercial if proyecto else f"Proyecto {asic.proyecto_id}"
        pct = float(asic.porcentaje_despacho or 0)
        if proyecto and proyecto.sub_project:
            plants_with_id.append({
                "nombre": nombre,
                "sub_project": proyecto.sub_project,
                "pct_despacho": pct,
            })
        else:
            sin_api_id.append(nombre)
            plants_without_id.append({"nombre": nombre, "pct_despacho": pct})

    if plants_with_id:
        try:
            token = _unergy_token()
        except Exception as exc:
            logger.error("No se pudo autenticar con la API de Unergy: %s", exc)
            raise HTTPException(503, "No se pudo autenticar con la API de Unergy")

        def _fetch_one(p: dict) -> dict:
            gen = _fetch_month(token, p["sub_project"], year, month)
            gen_planta = gen["mwh"]
            gen_contrato = round(gen_planta * p["pct_despacho"] / 100, 3) if gen_planta is not None else None
            return {
                "nombre": p["nombre"],
                "sub_project": p["sub_project"],
                "pct_despacho": p["pct_despacho"],
                "gen_planta_mwh": gen_planta,
                "gen_contrato_mwh": gen_contrato,
                "n_registros": gen["n_records"],
                "ultimo_dia": gen["ultimo_dia"],
                "sin_datos": gen_planta is None,
                "sin_api_id": False,
            }

        max_workers = min(len(plants_with_id), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_fetch_one, plants_with_id))
        plantas_data.extend(results)

    for p in plants_without_id:
        plantas_data.append({
            "nombre": p["nombre"],
            "sub_project": None,
            "pct_despacho": p["pct_despacho"],
            "gen_planta_mwh": None,
            "gen_contrato_mwh": None,
            "n_registros": 0,
            "ultimo_dia": None,
            "sin_datos": True,
            "sin_api_id": True,
        })

    # ── 6. Totales ────────────────────────────────────────────
    gen_total = round(
        sum(p["gen_contrato_mwh"] for p in plantas_data if p["gen_contrato_mwh"] is not None),
        3,
    )
    plantas_sin_datos = [p["nombre"] for p in plantas_data if p["sin_datos"]]

    # Proyección lineal al fin de mes (solo mes actual)
    if es_mes_actual and dia_actual > 0 and gen_total > 0:
        gen_proyectada = round(gen_total * total_dias / dia_actual, 3)
    else:
        gen_proyectada = gen_total

    # Día del último dato más antiguo entre plantas con datos
    dias_ultimo_dato = [p["ultimo_dia"] for p in plantas_data if p["ultimo_dia"] is not None]
    dia_min_datos = min(dias_ultimo_dato) if dias_ultimo_dato else None
    dia_max_datos = max(dias_ultimo_dato) if dias_ultimo_dato else None

    # ── 7. Balance ────────────────────────────────────────────
    min_mwh: Optional[float] = float(compromiso.energia_minima) if compromiso and compromiso.energia_minima is not None else None
    max_mwh: Optional[float] = float(compromiso.energia_maxima) if compromiso and compromiso.energia_maxima is not None else None

    val_balance = gen_proyectada if es_mes_actual else gen_total

    if min_mwh is not None and max_mwh is not None:
        if val_balance < min_mwh:
            estado = "deficit"
        elif val_balance > max_mwh:
            estado = "excedente"
        else:
            estado = "ok"
        compras = round(max(0.0, min_mwh - val_balance), 3)
        excedentes = round(max(0.0, val_balance - max_mwh), 3)
        margen = round(max_mwh - val_balance, 3)
    else:
        estado = "sin_compromisos"
        compras = excedentes = margen = None

    return {
        "contrato": {
            "id": contrato.id,
            "nombre_interno": contrato.nombre_interno,
            "numero_codigo_contrato": contrato.numero_codigo_contrato,
            "comprador_nombre": contrato.comprador_nombre,
            "fecha_inicio": contrato.fecha_inicio.isoformat() if contrato.fecha_inicio else None,
            "fecha_fin": contrato.fecha_fin.isoformat() if contrato.fecha_fin else None,
        },
        "periodo": {
            "year": year,
            "month": month,
            "dia_actual": dia_actual,
            "dias_mes": total_dias,
            "es_mes_actual": es_mes_actual,
            "dia_min_datos": dia_min_datos,
            "dia_max_datos": dia_max_datos,
        },
        "compromisos": {
            "energia_minima_mwh": min_mwh,
            "energia_maxima_mwh": max_mwh,
        },
        "generacion": {
            "gen_total_mwh": gen_total,
            "gen_proyectada_mwh": gen_proyectada,
            "tarifa_cop_kwh": float(tarifa_row.tarifa) if tarifa_row and tarifa_row.tarifa else None,
            "plantas": plantas_data,
            "plantas_sin_datos": plantas_sin_datos,
            "sin_api_id": sin_api_id,
            "n_plantas_activas": len(assignments),
        },
        "balance": {
            "estado": estado,
            "compras_bolsa_mwh": compras,
            "excedentes_bolsa_mwh": excedentes,
            "margen_mwh": margen,
        },
    }
