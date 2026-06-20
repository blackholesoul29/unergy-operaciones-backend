"""Control de Generación — curvas Quoia + Fusion/Solenium del día anterior.

Endpoints:
  GET /control-generacion/proyectos  → lista proyectos configurados
  GET /control-generacion/datos      → curvas Quoia + Solenium por proyecto y fecha
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("control_generacion")
router = APIRouter(prefix="/control-generacion", tags=["Control de Generación"])

_TIPOS_GENERACION = {"generacion", "generacion_consumo"}

_solenium: SoleniumClient | None = None
_gaia: GaiaClient | None = None


def _get_solenium() -> SoleniumClient:
    global _solenium
    if _solenium is None:
        _solenium = SoleniumClient()
    return _solenium


def _get_gaia() -> GaiaClient:
    global _gaia
    if _gaia is None:
        _gaia = GaiaClient()
    return _gaia


def _col_yesterday() -> str:
    col = datetime.now(timezone.utc) - timedelta(hours=5)
    return (col - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Helpers de extracción ──────────────────────────────────────────────────────

def _quoia_curve(gaia: GaiaClient, frt_code: str, fecha: str) -> dict:
    """Curva horaria eae (kWh) y total para una frontera Quoia por código SIC."""
    try:
        rows = gaia.get_border_measurements(frt_code, fecha)
    except Exception as exc:
        logger.warning("gaia border=%s fecha=%s error: %s", frt_code, fecha, exc)
        rows = []

    curva: list[dict] = []
    total = 0.0
    for row in rows:
        t = row.get("time", "")
        hora = t[11:16] if len(t) >= 16 else t
        kwh = float(row.get("eae", 0) or 0)
        total += kwh
        curva.append({"hora": hora, "kwh": round(kwh, 3)})

    return {"total_kwh": round(total, 3), "curva": curva}


def _solenium_inversores(sol: SoleniumClient, sol_id: int, fecha: str) -> dict:
    """Curva por inversor (5 min, kW) y total kWh para un proyecto Solenium."""
    try:
        data = sol.get_power(sol_id, date_from=fecha, date_to=fecha)
    except Exception as exc:
        logger.warning("solenium id=%s fecha=%s error: %s", sol_id, fecha, exc)
        data = None

    if not data:
        return {"total_kwh": 0.0, "inversores": []}

    # La respuesta puede ser lista o dict con distintas claves según el endpoint
    if isinstance(data, list):
        inverters_raw = data
    elif isinstance(data, dict):
        inverters_raw = (
            data.get("results")
            or data.get("inverters")
            or data.get("data")
            or []
        )
    else:
        inverters_raw = []

    inversores: list[dict] = []
    total = 0.0

    for inv in inverters_raw:
        inv_id   = inv.get("id") or inv.get("inverter_id")
        inv_name = (inv.get("name") or inv.get("inverter_name") or f"Inversor {inv_id}").strip()
        curve_raw = (
            inv.get("power")
            or inv.get("power_curve")
            or inv.get("curve")
            or inv.get("data")
            or []
        )
        curva: list[dict] = []
        inv_total = 0.0
        for pt in curve_raw:
            t  = pt.get("time") or pt.get("timestamp") or ""
            kw = float(pt.get("kw") or pt.get("power") or pt.get("value") or 0.0)
            # Integrar 5-min de potencia → energía (kWh)
            inv_total += kw * (5 / 60)
            hora = t[11:16] if len(t) >= 16 else t
            curva.append({"tiempo": hora, "kw": round(kw, 3)})
        inversores.append({
            "id": inv_id,
            "nombre": inv_name,
            "total_kwh": round(inv_total, 3),
            "curva": curva,
        })
        total += inv_total

    return {"total_kwh": round(total, 3), "inversores": inversores}


def _discrepancia(q_kwh: float, s_kwh: float) -> float | None:
    ref = max(q_kwh, s_kwh)
    if ref == 0:
        return None
    return round(abs(q_kwh - s_kwh) / ref * 100, 1)


def _safe_sol_id(val) -> int | None:
    if not val:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _query_fronteras_gen(db: Session, proyecto_ids: list) -> dict:
    """Devuelve {proyecto_id: [filas]} solo con las columnas que necesitamos."""
    if not proyecto_ids:
        return {}
    rows = db.execute(
        select(
            Frontera.proyecto_id,
            Frontera.id,
            Frontera.codigo_frontera,
            Frontera.tipo_frontera,
        ).where(
            Frontera.proyecto_id.in_(proyecto_ids),
            Frontera.tipo_frontera.in_(list(_TIPOS_GENERACION)),
        )
    ).fetchall()
    result: dict = defaultdict(list)
    for row in rows:
        result[row.proyecto_id].append(row)
    return result


@router.get("/proyectos")
def listar_proyectos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista proyectos de generación que tienen Solenium o Quoia configurado."""
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    frt_by_proj = _query_fronteras_gen(db, [p.id for p in proyectos])

    result = []
    for p in proyectos:
        fronteras_gen = frt_by_proj.get(p.id, [])
        tiene_solenium = bool(_safe_sol_id(p.project_id_solenium))
        tiene_quoia    = any(f.codigo_frontera for f in fronteras_gen)
        if not tiene_solenium and not tiene_quoia:
            continue
        result.append({
            "id":             p.id,
            "nombre":         p.nombre_comercial,
            "potencia_kwp":   float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
            "solenium_id":    _safe_sol_id(p.project_id_solenium),
            "tiene_quoia":    tiene_quoia,
            "tiene_solenium": tiene_solenium,
            "fronteras": [
                {"id": f.id, "codigo": f.codigo_frontera}
                for f in fronteras_gen
            ],
        })
    return {"proyectos": result}


@router.get("/datos")
def datos_generacion(
    fecha: str | None = Query(None, description="YYYY-MM-DD. Por defecto: ayer en hora Colombia"),
    proyecto_id: int | None = Query(None, description="Filtrar un proyecto específico"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Retorna curvas Quoia + Solenium/Fusion por proyecto para una fecha.
    Las llamadas a las APIs externas corren en paralelo (ThreadPoolExecutor).
    """
    if not fecha:
        fecha = _col_yesterday()
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status_code=422, detail="fecha debe tener formato YYYY-MM-DD")

    sol  = _get_solenium()
    gaia = _get_gaia()

    q = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
    )
    if proyecto_id:
        q = q.filter(Proyecto.id == proyecto_id)
    proyectos = q.all()

    frt_by_proj = _query_fronteras_gen(db, [p.id for p in proyectos])

    def _procesar(p: Proyecto) -> dict | None:
        fronteras_gen = frt_by_proj.get(p.id, [])
        sol_id = _safe_sol_id(p.project_id_solenium)

        if not fronteras_gen and sol_id is None:
            return None

        frontera_codigo = next((f.codigo_frontera for f in fronteras_gen if f.codigo_frontera), None)

        quoia_data    = {"total_kwh": 0.0, "curva": []}
        solenium_data = {"total_kwh": 0.0, "inversores": []}

        if frontera_codigo:
            quoia_data = _quoia_curve(gaia, frontera_codigo, fecha)
        if sol_id:
            solenium_data = _solenium_inversores(sol, sol_id, fecha)

        q_kwh = quoia_data["total_kwh"]
        s_kwh = solenium_data["total_kwh"]

        if q_kwh == 0 and s_kwh == 0:
            estado = "sin_medidas"
        else:
            estado = "con_datos"

        return {
            "proyecto_id":    p.id,
            "nombre":         p.nombre_comercial,
            "potencia_kwp":   float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
            "solenium_id":    sol_id,
            "frontera_codigo": frontera_codigo,
            "estado":         estado,
            "discrepancia_pct": _discrepancia(q_kwh, s_kwh),
            "quoia":    quoia_data,
            "solenium": solenium_data,
        }

    resultados: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_procesar, p): p for p in proyectos}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    resultados.append(res)
            except Exception as exc:
                logger.error("error procesando proyecto: %s", exc)

    resultados.sort(key=lambda x: x["nombre"])

    return {
        "fecha": fecha,
        "resumen": {
            "total_proyectos":    len(resultados),
            "con_datos":          sum(1 for r in resultados if r["estado"] == "con_datos"),
            "sin_medidas":        sum(1 for r in resultados if r["estado"] == "sin_medidas"),
            "total_quoia_kwh":    round(sum(r["quoia"]["total_kwh"] for r in resultados), 2),
            "total_solenium_kwh": round(sum(r["solenium"]["total_kwh"] for r in resultados), 2),
        },
        "proyectos": resultados,
    }
