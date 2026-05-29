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
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.services.mgs.gaia_client import GaiaClient, find_gaia_node_id
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("generacion_solar")
router = APIRouter(prefix="/generacion-solar", tags=["Generación Solar (Solenium)"])

_client: SoleniumClient | None = None
_gaia_client: GaiaClient | None = None


def _get_client() -> SoleniumClient:
    global _client
    if _client is None:
        _client = SoleniumClient()
    if not _client.enabled:
        raise HTTPException(503, "Solenium credentials not configured")
    return _client


def _get_gaia() -> GaiaClient | None:
    """Returns the GaiaClient if credentials are configured, else None (non-fatal)."""
    global _gaia_client
    if _gaia_client is None:
        _gaia_client = GaiaClient()
    return _gaia_client if _gaia_client.enabled else None


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


def _extract_strings(detail: dict) -> list[dict]:
    """Extract DC string data from a raw Solenium inverter-detail response.

    Tries multiple naming conventions:
    • vpv1/ipv1 … vpvN/ipvN  (most common)
    • pv{N}vol / pv{N}cur
    • u_pv{N} / i_pv{N}
    • mppt{N}_vpv / mppt{N}_ipv
    • nested list under key "pv" or "strings"
    """
    raw = detail
    if isinstance(detail, dict):
        raw = detail.get("results") or detail
    if not isinstance(raw, dict):
        return []

    strings: list[dict] = []

    # ── Pattern 1: numbered flat keys ─────────────────────────────────────────
    for i in range(1, 25):
        vpv = None
        ipv = None

        for key in (f"vpv{i}", f"pv{i}vol", f"pv{i}_vol",
                    f"u_pv{i}", f"mppt{i}_vpv", f"string{i}_v"):
            v = raw.get(key)
            if v is not None:
                try:
                    vpv = float(v)
                    break
                except (ValueError, TypeError):
                    pass

        for key in (f"ipv{i}", f"pv{i}cur", f"pv{i}_cur",
                    f"i_pv{i}", f"mppt{i}_ipv", f"string{i}_i"):
            v = raw.get(key)
            if v is not None:
                try:
                    ipv = float(v)
                    break
                except (ValueError, TypeError):
                    pass

        if vpv is None and ipv is None:
            break

        ppv = round(vpv * ipv / 1000, 3) if (vpv is not None and ipv is not None) else None
        strings.append({
            "string": i,
            "label": f"S{i}",
            "voltage_v": round(vpv, 1) if vpv is not None else None,
            "current_a": round(ipv, 2) if ipv is not None else None,
            "power_kw": ppv,
        })

    if strings:
        return strings

    # ── Pattern 2: list under "pv" or "strings" key ───────────────────────────
    for list_key in ("pv", "strings", "mppt"):
        items = raw.get(list_key)
        if isinstance(items, list):
            for j, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    continue
                vpv_raw = item.get("vpv") or item.get("voltage") or item.get("vol")
                ipv_raw = item.get("ipv") or item.get("current") or item.get("cur")
                vpv = float(vpv_raw) if vpv_raw is not None else None
                ipv = float(ipv_raw) if ipv_raw is not None else None
                ppv = round(vpv * ipv / 1000, 3) if (vpv is not None and ipv is not None) else None
                strings.append({
                    "string": j,
                    "label": f"S{j}",
                    "voltage_v": round(vpv, 1) if vpv is not None else None,
                    "current_a": round(ipv, 2) if ipv is not None else None,
                    "power_kw": ppv,
                })
            if strings:
                return strings

    return strings


def _extract_ac_metrics(detail: dict) -> dict:
    """Extract AC/electrical metrics from a raw Solenium inverter-detail response.

    Returns a dict with normalized keys. Values are floats or None when absent.
    pac_kw and qac_kvar are converted from W/VAr if the value seems to be in those units.
    """
    raw = detail
    if isinstance(detail, dict):
        raw = detail.get("results") or detail
    if not isinstance(raw, dict):
        return {}

    def _get(*keys):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return None

    pac_raw = _get("pac", "active_power", "p_ac", "pac_w", "power_ac")
    qac_raw = _get("qac", "reactive_power", "q_ac", "qac_w", "reactive_ac")

    # Heuristic: if value > 500, it is probably in W → convert to kW
    def _to_kw(v):
        if v is None:
            return None
        return round(v / 1000, 3) if abs(v) > 500 else round(v, 3)

    return {
        "vac_a":        _get("vac_a", "ua", "voltage_a", "v_a", "u_a", "u1", "uac_a"),
        "vac_b":        _get("vac_b", "ub", "voltage_b", "v_b", "u_b", "u2", "uac_b"),
        "vac_c":        _get("vac_c", "uc", "voltage_c", "v_c", "u_c", "u3", "uac_c"),
        "iac_a":        _get("iac_a", "ia", "current_a", "i_a", "i1", "iac_l1"),
        "iac_b":        _get("iac_b", "ib", "current_b", "i_b", "i2", "iac_l2"),
        "iac_c":        _get("iac_c", "ic", "current_c", "i_c", "i3", "iac_l3"),
        "power_factor": _get("pf", "power_factor", "cos_phi", "pf_total", "power_factor_total"),
        "pac_kw":       _to_kw(pac_raw),
        "qac_kvar":     _to_kw(qac_raw),
        "efficiency_pct": _get("efficiency", "eff", "efficiency_pct", "total_efficiency"),
        "e_day_kwh":    _get("eday", "e_day", "daily_energy", "today_energy",
                             "daily_gen", "generation_today", "etotal_today"),
        "temperature_c": _get("temperature", "temp", "t_inner", "inner_temp", "module_temp"),
    }


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


@router.get("/monitoring")
def fleet_monitoring(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Fleet monitoring: only DB projects with project_id_solenium set.
    Returns status (online/caido/degradado/sin_comunicacion) per project.
    Status determined by Solenium availability category:
      disconnect → sin_comunicacion
      critical   → caido
      low/medium → degradado
      high       → online
    """
    client = _get_client()

    proyectos = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
        Proyecto.project_id_solenium.isnot(None),
        Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
        Proyecto.srv_operacion == True,  # noqa: E712
    ).all()

    if not proyectos:
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "fleet": {"total": 0, "online": 0, "caido": 0, "degradado": 0,
                      "sin_comunicacion": 0, "total_power_kw": 0,
                      "total_capacity_kwp": 0, "utilization_pct": 0},
            "projects": [],
        }

    avail_map = client.get_availability()   # {sol_id_int: {name, availability, category}}

    summary_list = client.get_project_summary()
    summary_map: dict[int, dict] = {}
    for s in summary_list:
        pid = s.get("project_id") or s.get("id")
        if pid is not None:
            summary_map[int(pid)] = s

    today_str = date.today().isoformat()
    today_rows = db.execute(
        text("SELECT proyecto_id, kwh_real FROM generacion_diaria "
             "WHERE fecha = :today AND kwh_real IS NOT NULL"),
        {"today": today_str},
    ).fetchall()
    today_gen_map = {int(r.proyecto_id): float(r.kwh_real) for r in today_rows}

    projects_result = []
    total_power = 0.0
    total_capacity = 0.0
    counts = {"online": 0, "caido": 0, "degradado": 0, "sin_comunicacion": 0}

    for p in proyectos:
        sol_id = int(p.project_id_solenium)
        avail   = avail_map.get(sol_id, {})
        summary = summary_map.get(sol_id, {})

        availability_cat = avail.get("category", "disconnect")
        power_kw     = float(summary.get("power_kw") or 0)
        capacity_kwp = float(p.potencia_instalada_kwp or 0)
        energy_today = today_gen_map.get(p.id)

        if availability_cat == "disconnect":
            status = "sin_comunicacion"
        elif availability_cat == "critical":
            status = "caido"
        elif availability_cat in ("low", "medium"):
            status = "degradado"
        else:
            status = "online"

        counts[status] += 1
        total_power    += power_kw
        total_capacity += capacity_kwp

        projects_result.append({
            "proyecto_id":           p.id,
            "nombre":                p.nombre_comercial,
            "sol_id":                sol_id,
            "status":                status,
            "availability_category": availability_cat,
            "availability_pct":      avail.get("availability"),
            "power_kw":              round(power_kw, 2),
            "capacity_kwp":          round(capacity_kwp, 1),
            "utilization_pct":       round(power_kw / capacity_kwp * 100, 1) if capacity_kwp > 0 else 0,
            "energy_today_kwh":      energy_today,
            "last_update":           summary.get("power_time"),
        })

    _order = {"caido": 0, "sin_comunicacion": 1, "degradado": 2, "online": 3}
    projects_result.sort(key=lambda x: (_order.get(x["status"], 4), -(x["power_kw"] or 0)))

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "fleet": {
            "total":              len(proyectos),
            "online":             counts["online"],
            "caido":              counts["caido"],
            "degradado":          counts["degradado"],
            "sin_comunicacion":   counts["sin_comunicacion"],
            "total_power_kw":     round(total_power, 1),
            "total_capacity_kwp": round(total_capacity, 1),
            "utilization_pct":    round(total_power / total_capacity * 100, 1) if total_capacity > 0 else 0,
        },
        "projects": projects_result,
    }


@router.get("/monitoring/{proyecto_id}")
def project_monitoring_detail(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Detail monitoring for one project: inverter status + power curve today + 30d generation.
    Uses our internal proyecto_id, resolves to Solenium ID via project_id_solenium.
    """
    from concurrent.futures import ThreadPoolExecutor

    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    if not p.project_id_solenium:
        raise HTTPException(422, "Proyecto sin ID Solenium")

    sol_id = int(p.project_id_solenium)
    client = _get_client()

    today   = date.today()
    start30 = (today - timedelta(days=29)).isoformat()

    # Resolve Gaia node_id for this project (non-fatal if not found)
    gaia    = _get_gaia()
    node_id = find_gaia_node_id(
        p.nombre_comercial or "",
        p.alias_monitoreo or "",
        p.nombre_bitacora or "",
    )

    with ThreadPoolExecutor(max_workers=4) as ex:
        inv_f  = ex.submit(client.get_project_inverters, sol_id)
        pow_f  = ex.submit(client.get_power, sol_id)
        gen_f  = ex.submit(client.get_generation, sol_id, start30, today.isoformat())
        gaia_f = ex.submit(gaia.get_node_electrical_snapshot, node_id) \
                 if (gaia and node_id) else None

    inverters  = inv_f.result() or []
    power_data = pow_f.result() or {}
    gen_raw    = gen_f.result() or {}
    gaia_snap  = gaia_f.result() if gaia_f else None

    # ── Fetch per-inverter detail in parallel (strings + AC metrics) ─────────
    def _fetch_detail(inv):
        inv_id = inv.get("id")
        if not inv_id:
            return inv_id, [], {}
        try:
            detail = client.get_inverter_detail(sol_id, inv_id) or {}
        except Exception as exc:
            logger.warning("inverter_detail failed sol=%d inv=%s: %s", sol_id, inv_id, exc)
            detail = {}
        return inv_id, _extract_strings(detail), _extract_ac_metrics(detail)

    detail_map: dict[int, dict] = {}
    if inverters:
        with ThreadPoolExecutor(max_workers=min(len(inverters), 10)) as ex:
            for inv_id, strings, ac in ex.map(_fetch_detail, inverters):
                if inv_id is not None:
                    detail_map[inv_id] = {"strings": strings, "ac_metrics": ac}

    # ── Inverter status ──────────────────────────────────────────────────────
    inv_powers = [float(inv.get("power") or inv.get("pac") or 0) for inv in inverters]
    avg_power  = sum(inv_powers) / len(inv_powers) if inv_powers else 0

    processed_inverters = []
    for inv, pwr in zip(inverters, inv_powers):
        state = (inv.get("state") or inv.get("status") or "").lower()
        if "disconnect" in state or "off" in state:
            inv_status = "sin_comunicacion"
        elif "fault" in state or "error" in state:
            inv_status = "caido"
        elif avg_power > 0 and pwr == 0:
            inv_status = "caido"
        elif avg_power > 0 and pwr < avg_power * 0.6:
            inv_status = "degradado"
        elif pwr > 0:
            inv_status = "online"
        else:
            inv_status = "offline"

        inv_id  = inv.get("id")
        detail  = detail_map.get(inv_id, {})
        processed_inverters.append({
            "id":         inv_id,
            "name":       inv.get("dev_name") or inv.get("name") or f"INV-{inv_id or '?'}",
            "state":      inv.get("state") or inv.get("status") or "—",
            "power_kw":   round(pwr, 2),
            "inv_status": inv_status,
            "strings":    detail.get("strings", []),
            "ac_metrics": detail.get("ac_metrics", {}),
        })

    # ── Power curve today: sum all inverters per timestamp ────────────────
    power_total: dict[str, float] = {}
    raw_power = {}
    if isinstance(power_data, dict):
        raw_power = (power_data.get("power")
                     or power_data.get("results", {}).get("power")
                     or {})
    for timeseries in raw_power.values():
        if isinstance(timeseries, dict):
            for ts, val in timeseries.items():
                power_total[ts] = power_total.get(ts, 0.0) + float(val or 0)

    power_curve = [
        {"time": ts, "kw": round(v, 2)}
        for ts, v in sorted(power_total.items())
    ]

    # ── 30d daily generation ─────────────────────────────────────────────
    gen_kwh: dict[str, float] = gen_raw.get("generation_kwh") or {}
    daily: dict[str, float] = {}
    for ts, v in gen_kwh.items():
        day = ts.split(" ")[0]
        daily[day] = daily.get(day, 0.0) + float(v)
    generation_30d = [
        {"date": d, "kwh": round(v, 1)}
        for d, v in sorted(daily.items())
    ]

    has_strings = any(inv.get("strings") for inv in processed_inverters)

    return {
        "proyecto_id":    p.id,
        "nombre":         p.nombre_comercial,
        "sol_id":         sol_id,
        "gaia_node_id":   node_id,
        "capacity_kwp":   float(p.potencia_instalada_kwp or 0),
        "inverters":      processed_inverters,
        "power_curve":    power_curve,
        "generation_30d": generation_30d,
        "total_30d_kwh":  round(sum(d["kwh"] for d in generation_30d), 1),
        "has_strings":    has_strings,
        "gaia_snapshot":  gaia_snap,
    }


