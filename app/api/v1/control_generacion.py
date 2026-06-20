"""Control de Generación — curvas Quoia + Fusion/Solenium del día anterior.

Endpoints:
  GET /control-generacion/proyectos  → lista fronteras de generación desde Quoia (enriquecidas con BD)
  GET /control-generacion/datos      → curvas Quoia + Solenium por frontera y fecha
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

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


# ── DB lookup ─────────────────────────────────────────────────────────────────

def _build_db_lookup(db: Session) -> dict[str, dict]:
    """Returns {frt_code_lower → {proyecto_id, nombre, solenium_id, potencia_kwp}} from Railway DB."""
    rows = db.execute(
        select(
            Frontera.codigo_frontera,
            Proyecto.id,
            Proyecto.nombre_comercial,
            Proyecto.project_id_solenium,
            Proyecto.potencia_instalada_kwp,
        )
        .join(Proyecto, Frontera.proyecto_id == Proyecto.id)
        .where(
            Proyecto.deleted_at.is_(None),
            Frontera.tipo_frontera.in_(list(_TIPOS_GENERACION)),
            Frontera.codigo_frontera.isnot(None),
        )
    ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        frt = (row.codigo_frontera or "").strip().lower()
        if frt:
            result[frt] = {
                "proyecto_id":  row.id,
                "nombre":       row.nombre_comercial,
                "solenium_id":  _safe_sol_id(row.project_id_solenium),
                "potencia_kwp": float(row.potencia_instalada_kwp) if row.potencia_instalada_kwp else None,
            }
    return result


def _parse_borders(borders: list[dict], db_lookup: dict) -> list[dict]:
    """Convert Quoia border list to enriched dicts using DB info where available."""
    result = []
    for b in borders:
        frt_gen = b.get("frt_generation")
        if not frt_gen:
            continue
        frt_code = (frt_gen.get("frt_code") or "").strip().lower()
        if not frt_code:
            continue

        db_info = db_lookup.get(frt_code, {})
        result.append({
            "frt_code":       frt_code,
            "nombre":         db_info.get("nombre") or b.get("name") or frt_code,
            "proyecto_id":    db_info.get("proyecto_id"),
            "solenium_id":    db_info.get("solenium_id"),
            "potencia_kwp":   db_info.get("potencia_kwp"),
            "tiene_solenium": bool(db_info.get("solenium_id")),
            "en_app":         bool(db_info),
            "estado_quoia":   frt_gen.get("status", ""),
        })
    result.sort(key=lambda x: x["nombre"])
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/proyectos")
def listar_proyectos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista todas las fronteras de generación registradas en Quoia, enriquecidas con datos de la BD."""
    gaia = _get_gaia()
    borders = gaia.get_all_borders()
    db_lookup = _build_db_lookup(db)
    return {"proyectos": _parse_borders(borders, db_lookup)}


@router.get("/datos")
def datos_generacion(
    fecha: str | None = Query(None, description="YYYY-MM-DD. Por defecto: ayer en hora Colombia"),
    frt_code: str | None = Query(None, description="Filtrar una frontera específica por código SIC"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Retorna curvas Quoia + Solenium/Fusion por frontera para una fecha.
    Fuente de verdad: Quoia (todas las fronteras). BD enriquece con nombre y Solenium.
    Las llamadas a APIs externas corren en paralelo (ThreadPoolExecutor).
    """
    if not fecha:
        fecha = _col_yesterday()
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status_code=422, detail="fecha debe tener formato YYYY-MM-DD")

    sol  = _get_solenium()
    gaia = _get_gaia()

    borders   = gaia.get_all_borders()
    db_lookup = _build_db_lookup(db)
    parsed    = _parse_borders(borders, db_lookup)

    if frt_code:
        parsed = [p for p in parsed if p["frt_code"] == frt_code.strip().lower()]

    def _procesar(p: dict) -> dict | None:
        sol_id = p["solenium_id"]

        quoia_data    = _quoia_curve(gaia, p["frt_code"], fecha)
        solenium_data = {"total_kwh": 0.0, "inversores": []}
        if sol_id:
            solenium_data = _solenium_inversores(sol, sol_id, fecha)

        q_kwh = quoia_data["total_kwh"]
        s_kwh = solenium_data["total_kwh"]
        estado = "sin_medidas" if q_kwh == 0 and s_kwh == 0 else "con_datos"

        return {
            "frt_code":        p["frt_code"],
            "nombre":          p["nombre"],
            "proyecto_id":     p["proyecto_id"],
            "potencia_kwp":    p["potencia_kwp"],
            "solenium_id":     sol_id,
            "en_app":          p["en_app"],
            "estado":          estado,
            "discrepancia_pct": _discrepancia(q_kwh, s_kwh),
            "quoia":    quoia_data,
            "solenium": solenium_data,
        }

    resultados: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_procesar, p): p for p in parsed}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    resultados.append(res)
            except Exception as exc:
                logger.error("error procesando frontera: %s", exc)

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
