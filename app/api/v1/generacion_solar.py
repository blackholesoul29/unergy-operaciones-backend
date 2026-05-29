"""Real-time solar generation from Solenium inverter API."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.models.proyectos import Proyecto
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("generacion_solar")
router = APIRouter(prefix="/generacion-solar", tags=["Generación Solar (Solenium)"])

_client: SoleniumClient | None = None


def _get_client() -> SoleniumClient:
    global _client
    if _client is None:
        _client = SoleniumClient()
    if not _client.enabled:
        raise HTTPException(503, "Solenium credentials not configured")
    return _client


def _normalize_name(s: str) -> str:
    """Normaliza nombre para comparación fuzzy: sin tildes, minúsculas, solo alfanumérico."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _find_solenium_id(p: Proyecto, sol_name_map: dict[str, int]) -> int | None:
    """Encuentra el Solenium project_id para un proyecto interno.

    Prioridad:
    1. Campo project_id_solenium (ID explícito).
    2. Coincidencia exacta de nombre normalizado.
    3. Coincidencia por subcadena (mínimo 5 chars).
    """
    # 1. ID explícito
    if p.project_id_solenium:
        try:
            return int(p.project_id_solenium)
        except (ValueError, TypeError):
            pass

    # 2/3. Matching por nombre
    candidates = [p.nombre_comercial, p.alias_monitoreo, p.nombre_bitacora]
    for name in candidates:
        norm = _normalize_name(name or "")
        if not norm:
            continue
        # Exacto
        if norm in sol_name_map:
            return sol_name_map[norm]
        # Subcadena (bidireccional)
        if len(norm) >= 5:
            for sol_norm, sol_id in sol_name_map.items():
                if len(sol_norm) >= 5 and (norm in sol_norm or sol_norm in norm):
                    return sol_id
    return None


@router.get("/proyecto/{proyecto_id}/historial")
def proyecto_historial(
    proyecto_id: int,
    fecha_inicio: str = Query(..., description="YYYY-MM-DD"),
    fecha_fin: str = Query(..., description="YYYY-MM-DD"),
    granularidad: str = Query("day", description="day | hour"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Generación histórica de un proyecto desde Solenium.

    Acepta el ID interno de nuestra BD y resuelve el Solenium project_id
    usando project_id_solenium.  Devuelve puntos diarios u horarios.

    Respuesta:
      {
        proyecto_id, nombre, sol_id,
        granularidad,           # 'day' | 'hour'
        puntos: [{ label, kwh }],
        total_kwh
      }
    """
    # 1. Buscar proyecto en nuestra BD
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")

    # 2. Resolver Solenium ID
    sol_id: int | None = None
    if p.project_id_solenium:
        try:
            sol_id = int(p.project_id_solenium)
        except (ValueError, TypeError):
            pass

    if sol_id is None:
        # Fallback: matching por nombre (por si la migración no corrió aún)
        client = _get_client()
        sol_projects = client.get_projects()
        sol_name_map = {_normalize_name(sp.get("name", "")): int(sp["id"]) for sp in sol_projects if sp.get("id")}
        sol_id = _find_solenium_id(p, sol_name_map)

    if sol_id is None:
        raise HTTPException(404, "Este proyecto no tiene ID en Solenium. Agrega project_id_solenium en la BD.")

    # 3. Llamar al endpoint de generación de Solenium
    client = _get_client()
    raw = client.get_generation(sol_id, fecha_inicio, fecha_fin) or {}

    # La generación viene en generation_kwh: {"2026-05-22 08:00": 123.4, ...}
    gen_kwh: dict[str, float] = raw.get("generation_kwh") or {}

    if granularidad == "hour":
        # Devolver cada punto horario directamente
        puntos = [
            {"label": ts, "kwh": round(float(v), 2)}
            for ts, v in sorted(gen_kwh.items())
        ]
    else:
        # Agregar por día: sumar todas las horas del mismo día
        daily: dict[str, float] = {}
        for ts, v in gen_kwh.items():
            day = ts.split(" ")[0]       # "2026-05-22 08:00" → "2026-05-22"
            daily[day] = daily.get(day, 0.0) + float(v)
        puntos = [
            {"label": day, "kwh": round(kwh, 1)}
            for day, kwh in sorted(daily.items())
        ]

    total_kwh = round(sum(pt["kwh"] for pt in puntos), 1)

    return {
        "proyecto_id": p.id,
        "nombre":      p.nombre_comercial,
        "sol_id":      sol_id,
        "granularidad": granularidad,
        "puntos":      puntos,
        "total_kwh":   total_kwh,
    }


@router.get("/generacion-hoy")
def generacion_hoy(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Generación real de HOY por proyecto, desde Solenium.
    Empareja proyectos por project_id_solenium (explícito) o por nombre (fuzzy).
    Devuelve proyecto_id, nombre y kwh_real para los gráficos de Monitoreo.
    """
    from concurrent.futures import ThreadPoolExecutor

    client = _get_client()

    # 1. Todos los proyectos Solenium → nombre_normalizado → sol_id
    sol_projects = client.get_projects()
    sol_name_map: dict[str, int] = {}
    for sp in sol_projects:
        pid = sp.get("id")
        name = sp.get("name") or ""
        if pid is not None:
            sol_name_map[_normalize_name(name)] = int(pid)
    logger.info("solenium projects loaded: %d", len(sol_projects))

    # 2. Summary batch (campo puede ser project_id o id según versión de la API)
    summary_list = client.get_project_summary()
    summary_map: dict[int, dict] = {}
    for s in summary_list:
        pid = s.get("project_id") or s.get("id")
        if pid is not None:
            summary_map[int(pid)] = s
    logger.info("solenium summary loaded: %d entries", len(summary_map))

    # 3. Todos nuestros proyectos en operación
    proyectos_db = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
    ).all()

    # 4. Emparejar proyectos con Solenium
    matched: list[tuple] = []   # (proyecto, sol_id, summary_or_None)
    for p in proyectos_db:
        sol_id = _find_solenium_id(p, sol_name_map)
        if sol_id is None:
            logger.debug("sin match solenium: proyecto_id=%d nombre='%s'", p.id, p.nombre_comercial)
            continue
        matched.append((p, sol_id, summary_map.get(sol_id)))

    logger.info("proyectos emparejados: %d / %d", len(matched), len(proyectos_db))

    # 5. Obtener kwh_real e indicador de fuente por proyecto
    #    Fuentes posibles:
    #    - "inversor"  → /project/{id}/generation/ → total_generation_kwh (kWh, datos de inversores)
    #    - "medidor"   → /project_detail/{id}/ → generation.value en MWh (medidor de frontera)
    #    - "sin_dato"  → ninguna fuente disponible
    today_str = date.today().isoformat()

    def _fetch_kwh(item: tuple) -> tuple:
        p, sol_id, s = item
        kwh = 0.0
        power_kw = float((s or {}).get("power_kw") or 0)
        fuente = "sin_dato"

        # Fuente 1: endpoint /generation/ (datos de inversores, en kWh)
        try:
            gen = client.get_generation(sol_id, today_str, today_str) or {}
            if "results" in gen:
                gen = gen["results"]
            kwh = float(gen.get("total_generation_kwh") or 0)
            if kwh > 0:
                fuente = "inversor"
        except Exception as exc:
            logger.warning("generation fallo sol_id=%d: %s", sol_id, exc)

        # Fuente 2: project_detail → generation.value en MWh (medidor de frontera)
        if kwh == 0.0:
            try:
                detail = client.get_project_detail(sol_id) or {}
                if "results" in detail:
                    detail = detail["results"]
                gen_detail = detail.get("generation") or {}
                if gen_detail and gen_detail.get("value"):
                    unit = gen_detail.get("unit", "kWh")
                    val = float(gen_detail["value"])
                    kwh = val * 1000 if unit == "MWh" else val
                    if kwh > 0:
                        fuente = "medidor"
            except Exception as exc:
                logger.warning("project_detail fallo sol_id=%d: %s", sol_id, exc)

        return (p.id, p.nombre_comercial, sol_id, round(kwh, 1), round(power_kw, 2), fuente)

    result = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for pid, nombre, sol_id, kwh_real, power_kw, fuente in executor.map(_fetch_kwh, matched):
            result.append({
                "proyecto_id": pid,
                "nombre":      nombre,
                "sol_id":      sol_id,
                "kwh_real":    kwh_real,
                "power_kw":    power_kw,
                "fuente":      fuente,
            })

    result.sort(key=lambda x: x["kwh_real"], reverse=True)
    return {
        "fecha":    date.today().isoformat(),
        "total":    round(sum(r["kwh_real"] for r in result), 1),
        "proyectos": result,
    }


@router.get("/debug-matching")
def debug_matching(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Debug: muestra qué proyectos Solenium tenemos y cómo emparejan con nuestra DB."""
    client = _get_client()

    sol_projects = client.get_projects()
    sol_name_map: dict[str, int] = {}
    for sp in sol_projects:
        pid = sp.get("id")
        name = sp.get("name") or ""
        if pid is not None:
            sol_name_map[_normalize_name(name)] = int(pid)

    proyectos_db = db.query(Proyecto).filter(Proyecto.estado == "en_operacion").all()

    matched = []
    unmatched_ours = []
    for p in proyectos_db:
        sol_id = _find_solenium_id(p, sol_name_map)
        if sol_id is not None:
            matched.append({"proyecto_id": p.id, "nombre": p.nombre_comercial, "sol_id": sol_id})
        else:
            unmatched_ours.append({"proyecto_id": p.id, "nombre": p.nombre_comercial,
                                   "alias": p.alias_monitoreo, "bitacora": p.nombre_bitacora})

    matched_sol_ids = {m["sol_id"] for m in matched}
    unmatched_solenium = [
        {"sol_id": sol_id, "nombre_norm": norm}
        for norm, sol_id in sol_name_map.items()
        if sol_id not in matched_sol_ids
    ]

    # Muestra el primer project_detail para ver qué campos devuelve la API
    first_detail = None
    if matched:
        first_detail = client.get_project_detail(matched[0]["sol_id"])

    # Summary sample
    summary_list = client.get_project_summary()
    first_summary = summary_list[0] if summary_list else None

    return {
        "solenium_total": len(sol_projects),
        "nuestros_en_operacion": len(proyectos_db),
        "matched": len(matched),
        "unmatched_ours": len(unmatched_ours),
        "matches": matched,
        "sin_match_nuestros": unmatched_ours,
        "sin_match_solenium": sorted(unmatched_solenium, key=lambda x: x["nombre_norm"]),
        "debug_project_detail_sample": first_detail,
        "debug_summary_sample": first_summary,
        "debug_solenium_names": [
            {"sol_id": sid, "nombre_norm": norm}
            for norm, sid in list(sol_name_map.items())[:30]
        ],
    }


@router.get("/fleet")
def fleet_summary(_=Depends(get_current_user)):
    """Fleet overview: all projects with current power and generation status."""
    client = _get_client()
    projects = client.get_projects()
    summary = client.get_project_summary()

    summary_map = {s["project_id"]: s for s in summary}

    result = []
    total_power_kw = 0.0
    total_capacity_kwp = 0.0
    online = 0

    for p in projects:
        pid = p["id"]
        s = summary_map.get(pid, {})
        power_kw = s.get("power_kw") or 0.0
        capacity = p.get("installed_capacity") or 0.0

        total_power_kw += power_kw
        total_capacity_kwp += capacity
        if power_kw > 0:
            online += 1

        result.append({
            "id": pid,
            "name": p.get("name", ""),
            "location": p.get("location", ""),
            "is_minifarm": p.get("is_minifarm", False),
            "capacity_kwp": capacity,
            "power_kw": power_kw,
            "power_time": s.get("power_time"),
            "irradiance_w_m2": s.get("irradiance_w_m2"),
            "frontier_kwh": s.get("frontier_generation_kwh"),
        })

    result.sort(key=lambda x: x["power_kw"], reverse=True)

    return {
        "total_projects": len(projects),
        "online": online,
        "total_power_kw": round(total_power_kw, 1),
        "total_capacity_kwp": round(total_capacity_kwp, 1),
        "utilization_pct": round(total_power_kw / total_capacity_kwp * 100, 1) if total_capacity_kwp > 0 else 0,
        "projects": result,
    }


@router.get("/fleet/minifarms")
def fleet_minifarms(_=Depends(get_current_user)):
    """Minifarm-only fleet overview."""
    client = _get_client()
    projects = client.get_projects()
    summary = client.get_project_summary()
    summary_map = {s["project_id"]: s for s in summary}

    result = []
    for p in projects:
        if not p.get("is_minifarm"):
            continue
        pid = p["id"]
        s = summary_map.get(pid, {})
        result.append({
            "id": pid,
            "name": p.get("name", ""),
            "location": p.get("location", ""),
            "capacity_kwp": p.get("installed_capacity") or 0,
            "power_kw": s.get("power_kw") or 0,
            "power_time": s.get("power_time"),
            "irradiance_w_m2": s.get("irradiance_w_m2"),
            "frontier_kwh": s.get("frontier_generation_kwh"),
        })

    result.sort(key=lambda x: x["power_kw"], reverse=True)
    return result


@router.get("/project/{project_id}")
def project_detail(project_id: int, _=Depends(get_current_user)):
    """Single project detail with inverter status."""
    client = _get_client()
    detail = client.get_project_detail(project_id)
    if not detail:
        raise HTTPException(404, "Proyecto no encontrado en Solenium")

    inverters = client.get_project_inverters(project_id)
    power = client.get_power(project_id)

    return {
        "project": detail,
        "inverters": inverters,
        "power_today": power,
    }


@router.get("/project/{project_id}/generation")
def project_generation(
    project_id: int,
    days: int = Query(30, ge=1, le=365),
    _=Depends(get_current_user),
):
    """Daily generation history for a project."""
    client = _get_client()
    end = date.today()
    start = end - timedelta(days=days)
    data = client.get_energy(
        project_id,
        granularity="day",
        date_from=start.isoformat(),
        date_to=end.isoformat(),
    )
    if not data:
        return {"project_id": project_id, "days": [], "total_kwh": 0}

    days_data = []
    if isinstance(data, dict):
        raw = data.get("results") or data.get("data") or data
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, (int, float)):
                    days_data.append({"date": k, "kwh": round(v, 2)})
                elif isinstance(v, dict) and "value" in v:
                    days_data.append({"date": k, "kwh": round(v["value"], 2)})
        elif isinstance(raw, list):
            days_data = raw

    total = sum(d.get("kwh", 0) for d in days_data)
    return {
        "project_id": project_id,
        "days": days_data,
        "total_kwh": round(total, 2),
    }


@router.get("/project/{project_id}/power")
def project_power(project_id: int, _=Depends(get_current_user)):
    """Today's power curve (5-min intervals) for a project."""
    client = _get_client()
    data = client.get_power(project_id)
    if not data:
        return {"project_id": project_id, "unit": "kW", "power": {}}
    return data


@router.get("/project/{project_id}/inverters")
def project_inverters(project_id: int, _=Depends(get_current_user)):
    """Live inverter status for a project."""
    client = _get_client()
    inverters = client.get_project_inverters(project_id)
    return {
        "project_id": project_id,
        "count": len(inverters),
        "inverters": inverters,
    }


@router.get("/fleet/history")
def fleet_generation_history(
    days: int = Query(30, ge=1, le=365),
    _=Depends(get_current_user),
):
    """Fleet-wide daily generation history from generacion_diaria."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT g.fecha, SUM(g.kwh_real) / 1000.0 AS mwh,
                   COUNT(DISTINCT g.proyecto_id) AS projects,
                   MAX(g.fuente) AS fuente
            FROM generacion_diaria g
            WHERE g.fecha >= CURRENT_DATE - :days * INTERVAL '1 day'
              AND g.kwh_real IS NOT NULL
            GROUP BY g.fecha
            ORDER BY g.fecha
        """), {"days": days}).fetchall()

        total_mwh = sum(float(r.mwh) for r in rows)
        return {
            "days": [
                {
                    "date": r.fecha.isoformat(),
                    "mwh": round(float(r.mwh), 2),
                    "projects": r.projects,
                    "fuente": r.fuente,
                }
                for r in rows
            ],
            "total_mwh": round(total_mwh, 2),
            "days_with_data": len(rows),
        }
    finally:
        db.close()


@router.get("/fleet/history/by-project")
def fleet_generation_by_project(
    days: int = Query(30, ge=1, le=365),
    _=Depends(get_current_user),
):
    """Per-project generation history from generacion_diaria."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT p.id, p.nombre AS name, p.potencia_instalada_kwp,
                   SUM(g.kwh_real) / 1000.0 AS mwh,
                   COUNT(g.fecha) AS days_with_data,
                   MAX(g.fecha) AS last_date
            FROM generacion_diaria g
            JOIN proyectos p ON g.proyecto_id = p.id
            WHERE g.fecha >= CURRENT_DATE - :days * INTERVAL '1 day'
              AND g.kwh_real IS NOT NULL
            GROUP BY p.id, p.nombre, p.potencia_instalada_kwp
            ORDER BY mwh DESC
        """), {"days": days}).fetchall()

        return [
            {
                "id": r.id,
                "name": r.name,
                "capacity_kwp": float(r.potencia_instalada_kwp) if r.potencia_instalada_kwp else None,
                "mwh": round(float(r.mwh), 2),
                "days_with_data": r.days_with_data,
                "last_date": r.last_date.isoformat() if r.last_date else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.post("/sync-generation")
def sync_generation(_=Depends(get_current_user)):
    """Trigger manual Solenium → generacion_diaria sync."""
    from app.main import _scheduled_generation_sync
    import threading
    threading.Thread(target=_scheduled_generation_sync, daemon=True).start()
    return {"status": "sync_started"}


@router.get("/data-completeness")
def data_completeness(
    year: int = Query(None, ge=2020, le=2050),
    month: int = Query(None, ge=1, le=12),
    _=Depends(get_current_user),
):
    """Show which projects have/lack generation data for a given month."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    days_in_month = (date(year + (month // 12), (month % 12) + 1, 1) - date(year, month, 1)).days if month < 12 else 31

    db = SessionLocal()
    try:
        return _data_completeness_query(db, year, month, today, days_in_month)
    finally:
        db.close()


def _data_completeness_query(db, year, month, today, days_in_month):
    projects = db.execute(text("""
        SELECT p.id, p.nombre_comercial, p.potencia_instalada_kwp,
               p.project_id_solenium, p.estado
        FROM proyectos p
        WHERE p.estado = 'en_operacion'
        ORDER BY p.nombre_comercial
    """)).fetchall()

    gen_data = db.execute(text("""
        SELECT proyecto_id,
               COUNT(*) as days_with_data,
               SUM(kwh_real) as total_kwh,
               MAX(fecha) as last_date,
               MAX(fuente) as fuente
        FROM generacion_diaria
        WHERE EXTRACT(YEAR FROM fecha) = :year
          AND EXTRACT(MONTH FROM fecha) = :month
          AND kwh_real IS NOT NULL
        GROUP BY proyecto_id
    """), {"year": year, "month": month}).fetchall()
    gen_map = {int(r.proyecto_id): r for r in gen_data}

    elapsed_days = min(today.day, days_in_month) if year == today.year and month == today.month else days_in_month

    result = []
    with_data = 0
    without_data = 0
    for p in projects:
        gen = gen_map.get(p.id)
        has_data = gen is not None and gen.days_with_data > 0
        if has_data:
            with_data += 1
        else:
            without_data += 1
        result.append({
            "proyecto_id": p.id,
            "nombre": p.nombre_comercial,
            "capacidad_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
            "has_solenium_id": p.project_id_solenium is not None,
            "days_with_data": gen.days_with_data if gen else 0,
            "days_expected": elapsed_days,
            "completeness_pct": round(gen.days_with_data / elapsed_days * 100, 0) if gen and elapsed_days > 0 else 0,
            "total_kwh": round(float(gen.total_kwh), 1) if gen and gen.total_kwh else 0,
            "last_date": gen.last_date.isoformat() if gen and gen.last_date else None,
            "fuente": gen.fuente if gen else None,
        })

    return {
        "year": year,
        "month": month,
        "days_elapsed": elapsed_days,
        "projects_total": len(result),
        "with_data": with_data,
        "without_data": without_data,
        "completeness_pct": round(with_data / len(result) * 100, 0) if result else 0,
        "projects": result,
    }


@router.get("/availability")
def fleet_availability(_=Depends(get_current_user)):
    """Fleet availability breakdown from Solenium."""
    client = _get_client()
    avail = client.get_availability()
    categories = {"high": [], "medium": [], "low": [], "critical": [], "disconnect": []}
    for pid, info in avail.items():
        cat = info.get("category", "disconnect")
        if cat in categories:
            categories[cat].append({
                "id": pid,
                "name": info.get("name", ""),
                "availability": info.get("availability"),
            })

    return {
        "total": len(avail),
        "categories": {
            k: {"count": len(v), "projects": v}
            for k, v in categories.items()
        },
    }
