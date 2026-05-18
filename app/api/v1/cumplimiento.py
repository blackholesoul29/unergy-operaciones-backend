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
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/",
                params={
                    "time_stamp__gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                    "limit": "10000",
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
        # La API devuelve timestamps con offset Colombia (-05:00) o Z.
        # fromisoformat los parsea correctamente — el .day es ya hora Colombia.
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        ultimo_dia = last_dt.day
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


@router.get("/ppa/resumen")
def get_resumen(
    year: int = Query(..., ge=2020, le=2050),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Resumen de cumplimiento de todos los contratos PPA para un período.
    Deduplica sub_projects y hace una sola llamada a la API por planta.
    """
    today = date.today()
    es_mes_actual = year == today.year and month == today.month
    total_dias = calendar.monthrange(year, month)[1]
    dia_actual = today.day if es_mes_actual else total_dias

    # ── 1. Contratos y compromisos ────────────────────────────────────────────
    contratos = (
        db.query(PPAContrato)
        .order_by(PPAContrato.nombre_interno.nullslast(), PPAContrato.id)
        .all()
    )
    compromisos_map = {
        c.contrato_id: c
        for c in db.query(PPACompromisoEnergia).filter(
            PPACompromisoEnergia.año == year,
            PPACompromisoEnergia.mes == month,
        ).all()
    }

    # ── 2. GESCON por contrato ────────────────────────────────────────────────
    contrato_assignments: dict[int, list] = {}
    for c in contratos:
        if c.numero_codigo_contrato:
            contrato_assignments[c.id] = _resolve_gescon(db, c.numero_codigo_contrato, year, month)
        else:
            contrato_assignments[c.id] = []

    # ── 3. Sub-projects únicos ────────────────────────────────────────────────
    sp_set: set[str] = set()
    for assignments in contrato_assignments.values():
        for asic in assignments:
            if asic.proyecto and asic.proyecto.sub_project:
                sp_set.add(asic.proyecto.sub_project)

    # ── 4. Generación en paralelo (un solo fetch por planta) ──────────────────
    gen_cache: dict[str, dict] = {}
    if sp_set:
        try:
            token = _unergy_token()
        except Exception as exc:
            logger.error("Auth Unergy failed in resumen: %s", exc)
            raise HTTPException(503, "No se pudo autenticar con la API de Unergy")

        sp_list = list(sp_set)

        def _fetch_sp(sp: str) -> tuple:
            return sp, _fetch_month(token, sp, year, month)

        max_workers = min(len(sp_list), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for sp, result in pool.map(_fetch_sp, sp_list):
                gen_cache[sp] = result

    # ── 5. Cálculo por contrato ────────────────────────────────────────────────
    contratos_result = []
    total_min = 0.0
    total_max = 0.0
    total_gen = 0.0
    total_proy = 0.0
    has_any_compromisos = False

    for c in contratos:
        assignments = contrato_assignments[c.id]
        compromiso = compromisos_map.get(c.id)

        gen_total_c = 0.0
        plantas_sin_datos: list[str] = []
        dias_datos: list[int] = []

        for asic in assignments:
            proyecto = asic.proyecto
            nombre = proyecto.nombre_comercial if proyecto else f"Proyecto {asic.proyecto_id}"
            pct = float(asic.porcentaje_despacho or 0)
            if proyecto and proyecto.sub_project:
                gd = gen_cache.get(proyecto.sub_project, {"mwh": None, "ultimo_dia": None})
                gp = gd["mwh"]
                if gp is not None:
                    gen_total_c += gp * pct
                    if gd.get("ultimo_dia") is not None:
                        dias_datos.append(gd["ultimo_dia"])
                else:
                    plantas_sin_datos.append(nombre)
            else:
                plantas_sin_datos.append(nombre)

        gen_total_c = round(gen_total_c, 3)
        gen_proy_c = (
            round(gen_total_c * total_dias / dia_actual, 3)
            if es_mes_actual and dia_actual > 0 and gen_total_c > 0
            else gen_total_c
        )

        min_mwh: Optional[float] = float(compromiso.energia_minima) if compromiso and compromiso.energia_minima is not None else None
        max_mwh: Optional[float] = float(compromiso.energia_maxima) if compromiso and compromiso.energia_maxima is not None else None

        val_b = gen_proy_c if es_mes_actual else gen_total_c

        if min_mwh is not None and max_mwh is not None:
            has_any_compromisos = True
            if val_b < min_mwh:
                estado_c = "deficit"
            elif val_b > max_mwh:
                estado_c = "excedente"
            else:
                estado_c = "ok"
            compras_c = round(max(0.0, min_mwh - val_b), 3)
            excedentes_c = round(max(0.0, val_b - max_mwh), 3)
            total_min += min_mwh
            total_max += max_mwh
        else:
            estado_c = "sin_compromisos"
            compras_c = None
            excedentes_c = None

        total_gen += gen_total_c
        total_proy += gen_proy_c

        contratos_result.append({
            "id": c.id,
            "nombre_interno": c.nombre_interno,
            "numero_codigo_contrato": c.numero_codigo_contrato,
            "comprador_nombre": c.comprador_nombre,
            "energia_minima_mwh": min_mwh,
            "energia_maxima_mwh": max_mwh,
            "gen_total_mwh": gen_total_c,
            "gen_proyectada_mwh": gen_proy_c,
            "estado": estado_c,
            "compras_bolsa_mwh": compras_c,
            "excedentes_bolsa_mwh": excedentes_c,
            "n_plantas_activas": len(assignments),
            "plantas_sin_datos": plantas_sin_datos,
            "dia_min_datos": min(dias_datos) if dias_datos else None,
        })

    # ── 6. Totales agregados ──────────────────────────────────────────────────
    total_gen = round(total_gen, 3)
    total_proy = round(total_proy, 3)
    val_total = total_proy if es_mes_actual else total_gen

    if has_any_compromisos and total_max > 0:
        if val_total < total_min:
            total_estado = "deficit"
        elif val_total > total_max:
            total_estado = "excedente"
        else:
            total_estado = "ok"
        total_compras = round(max(0.0, total_min - val_total), 3)
        total_excedentes = round(max(0.0, val_total - total_max), 3)
    else:
        total_estado = "sin_compromisos"
        total_compras = None
        total_excedentes = None

    dias_min_list = [c["dia_min_datos"] for c in contratos_result if c["dia_min_datos"] is not None]

    return {
        "periodo": {
            "year": year,
            "month": month,
            "dia_actual": dia_actual,
            "dias_mes": total_dias,
            "es_mes_actual": es_mes_actual,
            "dia_min_datos": min(dias_min_list) if dias_min_list else None,
            "dia_max_datos": max(dias_min_list) if dias_min_list else None,
        },
        "totales": {
            "energia_minima_mwh": round(total_min, 3) if has_any_compromisos else None,
            "energia_maxima_mwh": round(total_max, 3) if has_any_compromisos else None,
            "gen_total_mwh": total_gen,
            "gen_proyectada_mwh": total_proy,
            "estado": total_estado,
            "compras_bolsa_mwh": total_compras,
            "excedentes_bolsa_mwh": total_excedentes,
        },
        "contratos": contratos_result,
    }


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
            # porcentaje_despacho en ASIC es fracción 0-1 (1.0 = 100%)
            gen_contrato = round(gen_planta * p["pct_despacho"], 3) if gen_planta is not None else None
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
