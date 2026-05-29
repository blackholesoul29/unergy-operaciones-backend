"""Real-time solar generation from Solenium inverter API."""
from __future__ import annotations

import logging
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


@router.get("/generacion-hoy")
def generacion_hoy(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Generación real de HOY por proyecto, desde Solenium project_detail.
    Devuelve proyecto_id, nombre y kwh_real para los gráficos de Monitoreo.
    """
    client = _get_client()

    # 1. Summary en una sola llamada → {solenium_id: {frontier_generation_kwh, power_kw, ...}}
    summary_list = client.get_project_summary()
    summary_map: dict[int, dict] = {}
    for s in summary_list:
        pid = s.get("project_id")
        if pid is not None:
            summary_map[int(pid)] = s

    # 2. Proyectos con project_id_solenium
    proyectos_db = db.query(Proyecto).filter(
        Proyecto.project_id_solenium.isnot(None),
        Proyecto.estado == "en_operacion",
    ).all()

    result = []
    for p in proyectos_db:
        try:
            sol_id = int(p.project_id_solenium)
        except (ValueError, TypeError):
            continue

        s = summary_map.get(sol_id)

        # Intentar project_detail si el summary no trae generación
        kwh_real = 0.0
        if s:
            kwh_real = float(s.get("frontier_generation_kwh") or
                             s.get("energy_today_kwh") or
                             s.get("generation_today") or 0)
        if kwh_real == 0.0:
            # Fallback: project_detail/{id}/
            detail = client.get_project_detail(sol_id) or {}
            kwh_real = float(
                detail.get("frontier_generation_kwh") or
                detail.get("energy_today_kwh") or
                detail.get("generation_today") or
                detail.get("daily_generation") or 0
            )

        result.append({
            "proyecto_id": p.id,
            "nombre":      p.nombre_comercial,
            "sol_id":      sol_id,
            "kwh_real":    round(kwh_real, 1),
            "power_kw":    round(float((s or {}).get("power_kw") or 0), 2),
        })

    result.sort(key=lambda x: x["kwh_real"], reverse=True)
    return {
        "fecha":    date.today().isoformat(),
        "total":    round(sum(r["kwh_real"] for r in result), 1),
        "proyectos": result,
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
