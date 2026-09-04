"""Real-time solar generation from Solenium inverter API."""
from __future__ import annotations

import calendar
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.services.mgs.medidor_tiempo_real import elegir_medidor, snapshot_medidor
from app.services.mgs.gaia_client import (
    GaiaClient, build_db_proyecto_frt_map,
    find_gaia_node_id, find_gaia_node_pair,
)
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("generacion_solar")
router = APIRouter(prefix="/generacion-solar", tags=["Generación Solar (Solenium)"])

# Colombia opera en America/Bogota = UTC-5 (sin horario de verano). El servidor
# de producción (Railway) corre en UTC, por lo que `_hoy_col()` devuelve la
# fecha UTC y "hoy" se adelanta 5h: entre las 19:00 y medianoche de Bogotá el
# servidor ya está en el día siguiente y la "generación de hoy" salía casi en
# cero. Las claves de franja horaria de Solenium están en hora local de la
# planta (Bogotá), así que el día con el que se filtran/cachean debe ser el de
# Bogotá. Ver _COL_TZ usado igual en fallas.py / cumplimiento.py / desconexion.py.
_COL_TZ = timezone(timedelta(hours=-5))


def _hoy_col() -> date:
    """Fecha actual en hora de Colombia (Bogotá, UTC-5), independiente del TZ del servidor."""
    return datetime.now(_COL_TZ).date()

_client: SoleniumClient | None = None
_gaia_client: GaiaClient | None = None

# ── TTL cache en memoria ───────────────────────────────────────────────────────
# Evita llamar a Solenium/Gaia en cada request; se invalida solo pasado el TTL.
_cache: dict[str, tuple[float, object]] = {}   # key → (timestamp, data)

CACHE_TTL_FLEET  = 60    # segundos — fleet monitoring (datos de flota)
CACHE_TTL_DETAIL = 90    # segundos — detalle por proyecto
CACHE_TTL_GENHOY = 120   # segundos — generación de hoy


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < entry[1][0]:  # type: ignore[index]
        return entry[1][1]
    return None


def _cache_set(key: str, ttl: int, data: object) -> None:
    _cache[key] = (time.monotonic(), (ttl, data))


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
    candidates = [p.nombre_comercial]
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


def _sum_today_inverter_kwh(gen_kwh_map: dict, today_str: str) -> float:
    """Suma las entradas de HOY de un mapa generation_kwh de Solenium.

    `get_generation(ayer, hoy)` devuelve valores incrementales por franja horaria
    con claves tipo "2026-06-09 08:00"; nos quedamos solo con las de hoy."""
    if not gen_kwh_map:
        return 0.0
    total = 0.0
    for k, v in gen_kwh_map.items():
        if str(k).startswith(today_str):
            try:
                total += float(v)
            except (ValueError, TypeError):
                continue
    return total


def _meter_kwh_from_summary(summary: dict | None) -> float | None:
    """Energía del día del medidor (frontera) desde un item de project_summary."""
    if not summary:
        return None
    raw = summary.get("frontier_generation_kwh")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
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
    _GENHOY_KEY = f"genhoy:{_hoy_col().isoformat()}"
    cached = _cache_get(_GENHOY_KEY)
    if cached:
        return cached

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
    today_str = _hoy_col().isoformat()

    def _fetch_kwh(item: tuple) -> tuple:
        p, sol_id, s = item
        kwh = 0.0
        power_kw = float((s or {}).get("power_kw") or 0)
        fuente = "sin_dato"

        # Fuente 1: get_generation(ayer, hoy) → filtramos solo entradas de hoy.
        # Llamar con un solo día devuelve el acumulado histórico; con rango ayer→hoy
        # devuelve valores incrementales por franja horaria y filtramos las de hoy.
        try:
            from datetime import timedelta
            yesterday_str = (_hoy_col() - timedelta(days=1)).isoformat()
            gen = client.get_generation(sol_id, yesterday_str, today_str) or {}
            if "results" in gen:
                gen = gen["results"]
            gen_kwh_map = gen.get("generation_kwh") or {}
            kwh = sum(
                float(v or 0) for k, v in gen_kwh_map.items()
                if str(k).startswith(today_str)
            )
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
                    # Normalizar la unidad: Solenium puede devolver "MWh"/"Mwh"/"mwh".
                    # Comparar con == "MWh" exacto dejaba un valor en MWh sin escalar
                    # (1000× menos) si la etiqueta variaba de mayúsculas.
                    unit = (gen_detail.get("unit") or "kWh").strip().lower()
                    val = float(gen_detail["value"])
                    kwh = val * 1000 if unit == "mwh" else val
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
    data = {
        "fecha":    _hoy_col().isoformat(),
        "total":    round(sum(r["kwh_real"] for r in result), 1),
        "proyectos": result,
    }
    _cache_set(_GENHOY_KEY, CACHE_TTL_GENHOY, data)
    return data


@router.get("/resumen-dia")
def resumen_dia(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Resumen del día: top de generación por medidores y por inversores.

    - Medidor: `frontier_generation_kwh` del summary de Solenium (1 batch).
    - Inversor: `get_generation(ayer, hoy)` por proyecto, sumando las entradas de hoy
      (paralelo). Ambas listas ordenadas desc. Cacheado en memoria (TTL corto).
    """
    _KEY = f"resumendia:{_hoy_col().isoformat()}"
    cached = _cache_get(_KEY)
    if cached:
        return cached

    client = _get_client()
    today_str = _hoy_col().isoformat()
    yesterday_str = (_hoy_col() - timedelta(days=1)).isoformat()

    # Matching proyectos ↔ Solenium (mismo criterio que generacion-hoy)
    sol_projects = client.get_projects()
    sol_name_map: dict[str, int] = {}
    for sp in sol_projects:
        pid = sp.get("id")
        if pid is not None:
            sol_name_map[_normalize_name(sp.get("name") or "")] = int(pid)

    summary_list = client.get_project_summary()
    summary_map: dict[int, dict] = {}
    for s in summary_list:
        pid = s.get("project_id") or s.get("id")
        if pid is not None:
            summary_map[int(pid)] = s

    proyectos_db = db.query(Proyecto).filter(Proyecto.estado == "en_operacion").all()
    matched: list[tuple] = []
    for p in proyectos_db:
        sol_id = _find_solenium_id(p, sol_name_map)
        if sol_id is not None:
            matched.append((p, sol_id))

    # Medidor (frontera) desde el batch de summary — sin llamadas extra.
    medidor: list[dict] = []
    for p, sol_id in matched:
        kwh = _meter_kwh_from_summary(summary_map.get(sol_id))
        if kwh and kwh > 0:
            medidor.append({"proyecto_id": p.id, "nombre": p.nombre_comercial, "kwh": round(kwh, 1)})

    # Inversores desde get_generation (paralelo, como generacion-hoy).
    def _inv(item: tuple) -> tuple:
        p, sol_id = item
        try:
            gen = client.get_generation(sol_id, yesterday_str, today_str) or {}
            if "results" in gen:
                gen = gen["results"]
            kwh = _sum_today_inverter_kwh(gen.get("generation_kwh") or {}, today_str)
        except Exception as exc:
            logger.warning("resumen-dia inversor sol_id=%s: %s", sol_id, exc)
            kwh = 0.0
        return (p.id, p.nombre_comercial, round(kwh, 1))

    inversor: list[dict] = []
    if matched:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for pid, nombre, kwh in ex.map(_inv, matched):
                if kwh > 0:
                    inversor.append({"proyecto_id": pid, "nombre": nombre, "kwh": kwh})

    medidor.sort(key=lambda x: x["kwh"], reverse=True)
    inversor.sort(key=lambda x: x["kwh"], reverse=True)

    data = {
        "fecha":    today_str,
        "medidor":  {"total": round(sum(x["kwh"] for x in medidor), 1),  "top": medidor},
        "inversor": {"total": round(sum(x["kwh"] for x in inversor), 1), "top": inversor},
    }
    _cache_set(_KEY, CACHE_TTL_GENHOY, data)
    return data


@router.get("/monitoring")
def fleet_monitoring(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Fleet monitoring: DB projects en operación, minigranja y con servicio de
    operación. Si a alguno le falta project_id_solenium, se resuelve por
    coincidencia de nombre contra Solenium (igual que en /generacion-hoy) y se
    persiste en la BD, para no depender de asignarlo a mano cada vez que se
    activa un proyecto nuevo.
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

    # Caché de flota (evita llamadas Solenium por cada refresh)
    _FLEET_CACHE_KEY = f"fleet:{_hoy_col().isoformat()}"
    cached = _cache_get(_FLEET_CACHE_KEY)
    if cached:
        return cached

    sin_id = [p for p in proyectos if not p.project_id_solenium]

    # Paralelizar las llamadas Solenium que antes eran seriales. Solo se pide
    # get_projects() (para el matching por nombre) si hay algún proyecto sin
    # project_id_solenium asignado.
    with ThreadPoolExecutor(max_workers=3) as ex:
        avail_f    = ex.submit(client.get_availability)
        summary_f  = ex.submit(client.get_project_summary)
        projects_f = ex.submit(client.get_projects) if sin_id else None
    avail_map    = avail_f.result() or {}
    summary_list = summary_f.result() or []

    summary_map: dict[int, dict] = {}
    for s in summary_list:
        pid = s.get("project_id") or s.get("id")
        if pid is not None:
            summary_map[int(pid)] = s

    if sin_id:
        sol_name_map: dict[str, int] = {}
        for sp in (projects_f.result() or []):
            pid = sp.get("id")
            if pid is not None:
                sol_name_map[_normalize_name(sp.get("name") or "")] = int(pid)

        # project_id_solenium es único en la tabla: un mismo sol_id puede matchear
        # por nombre a dos proyectos internos distintos (ej. planta principal vs.
        # su proyecto de "excedentes"). Sin este chequeo, ese conflicto revienta
        # el UPDATE de TODOS los proyectos de este lote (misma transacción) y
        # ninguno queda asignado, aunque su match individual fuera correcto.
        used_ids = {
            v for (v,) in db.query(Proyecto.project_id_solenium)
                            .filter(Proyecto.project_id_solenium.isnot(None)).all()
        }

        for p in sin_id:
            sol_id = _find_solenium_id(p, sol_name_map)
            if sol_id is None:
                logger.warning("sin match solenium al auto-asignar: proyecto_id=%d nombre='%s'",
                                p.id, p.nombre_comercial)
                continue
            if str(sol_id) in used_ids:
                logger.warning(
                    "match ambiguo al auto-asignar: proyecto_id=%d nombre='%s' -> sol_id=%d "
                    "ya asignado a otro proyecto, requiere revisión manual",
                    p.id, p.nombre_comercial, sol_id)
                continue
            logger.info("auto-asignando project_id_solenium=%d a proyecto_id=%d nombre='%s'",
                        sol_id, p.id, p.nombre_comercial)
            p.project_id_solenium = str(sol_id)
            db.add(p)
            used_ids.add(str(sol_id))
        db.commit()

    today_str = _hoy_col().isoformat()
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
        try:
            sol_id = int(p.project_id_solenium)
        except (TypeError, ValueError):
            logger.warning("project_id_solenium inválido proyecto_id=%s valor=%r",
                            p.id, p.project_id_solenium)
            continue
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

    result = {
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
    _cache_set(_FLEET_CACHE_KEY, CACHE_TTL_FLEET, result)
    return result


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
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    # Sin id de Solenium NO se corta: los inversores quedan sin dato, pero el
    # medidor se resuelve por find_gaia_node_pair desde fronteras.proyecto_id,
    # un camino que no depende de ningun proveedor externo. Antes esto era un
    # 422 que dejaba la tarjeta entera vacia, incluida la mitad que si tenia
    # con que llenarse (2026-09-03).

    # Caché de detalle por proyecto (evita 21-30 llamadas externas por cada tarjeta)
    _detail_key = f"detail:{proyecto_id}:{_hoy_col().isoformat()}"
    cached = _cache_get(_detail_key)
    if cached:
        return cached

    sol_id = int(p.project_id_solenium) if p.project_id_solenium else None
    client = _get_client()

    today   = _hoy_col()
    start30 = (today - timedelta(days=29)).isoformat()

    # Resolve Gaia node IDs for this project (non-fatal if not found)
    gaia = _get_gaia()
    _db_fronteras = db.query(Frontera.proyecto_id, Frontera.codigo_frontera).filter(
        Frontera.tipo_frontera.in_([TipoFronteraEnum.generacion, TipoFronteraEnum.generacion_consumo]),
        Frontera.codigo_frontera.isnot(None),
    ).all()
    _db_proyecto_frt_map = build_db_proyecto_frt_map(list(_db_fronteras))
    node_principal, node_respaldo = find_gaia_node_pair(
        gaia=gaia,
        proyecto_id=p.id,
        db_proyecto_frt_map=_db_proyecto_frt_map,
    )

    hoy = today.isoformat()
    capacidad_mw = float(p.potencia_instalada_kwp or 0) / 1000 or None
    with ThreadPoolExecutor(max_workers=6) as ex:
        inv_f      = ex.submit(client.get_project_inverters, sol_id) if sol_id else None
        pow_f      = ex.submit(client.get_power, sol_id, hoy, hoy) if sol_id else None
        gen_f      = ex.submit(client.get_energy, sol_id, granularity="day",
                               date_from=start30, date_to=today.isoformat()) if sol_id else None
        gen_hoy_f  = ex.submit(client.get_generation, sol_id, hoy, hoy) if sol_id else None
        # Medidor: `ap` + `eae` por el mismo metodo que usa el pipeline del
        # ASIC, en vez del compuesto de 8 familias de variables (que para dos
        # nodos eran hasta 16 llamadas externas por tarjeta). Ver
        # services/mgs/medidor_tiempo_real.py.
        med_p_f    = ex.submit(snapshot_medidor, gaia, node_principal, hoy, capacidad_mw) if (gaia and node_principal) else None
        med_r_f    = ex.submit(snapshot_medidor, gaia, node_respaldo, hoy, capacidad_mw) if (gaia and node_respaldo) else None

    inverters  = (inv_f.result() or []) if inv_f else []
    power_data = (pow_f.result() or {}) if pow_f else {}
    gen_raw    = (gen_f.result() or {}) if gen_f else {}
    gen_hoy    = (gen_hoy_f.result() or {}) if gen_hoy_f else {}
    # Total real de hoy calculado por Solenium (endpoint /generation/, más preciso
    # que integrar nosotros la curva de potencia de 5 min por trapecios).
    generation_today_kwh = gen_hoy.get("total_generation_kwh")

    med_p = med_p_f.result() if med_p_f else None
    med_r = med_r_f.result() if med_r_f else None

    # La eleccion vive SOLO aca. Antes el mismo criterio ("mayor energia")
    # estaba escrito tambien en SolarLiveView.vue, y podian desincronizarse en
    # silencio: la grafica mostrando un medidor y el resto de la tarjeta otro.
    medidor, medidor_tipo = elegir_medidor(med_p, med_r)
    best_node = medidor["node_id"] if medidor else (node_principal or node_respaldo)

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

    # ── 30d daily generation (desde get_energy granularity=day) ─────────────
    gen_results = gen_raw.get("results") if isinstance(gen_raw, dict) else None
    gen_points = gen_results.get("points") if isinstance(gen_results, dict) else None
    gen_unit = (gen_results.get("unit") or "kWh").strip().lower() if isinstance(gen_results, dict) else "kwh"
    gen_factor = 1000.0 if gen_unit == "mwh" else 1.0

    daily: dict[str, float] = {}
    if isinstance(gen_points, list):
        for item in gen_points:
            if not isinstance(item, dict):
                continue
            d = item.get("time") or item.get("date") or item.get("day")
            val = item.get("kwh")
            if val is None:
                val = item.get("value") or item.get("energy")
            if d and val is not None:
                d = str(d)[:10]
                daily[d] = daily.get(d, 0.0) + float(val) * gen_factor
    generation_30d = [
        {"date": d, "kwh": round(v, 1)}
        for d, v in sorted(daily.items())
    ]

    has_strings = any(inv.get("strings") for inv in processed_inverters)

    result = {
        "proyecto_id":            p.id,
        "nombre":                 p.nombre_comercial,
        "sol_id":                 sol_id,
        "gaia_node_id":           best_node,
        "gaia_node_principal":    node_principal,
        "gaia_node_respaldo":     node_respaldo,
        "capacity_kwp":           float(p.potencia_instalada_kwp or 0),
        "inverters":              processed_inverters,
        "power_curve":            power_curve,
        "generation_today_kwh":   round(generation_today_kwh, 1) if generation_today_kwh is not None else None,
        "generation_30d":         generation_30d,
        "total_30d_kwh":          round(sum(d["kwh"] for d in generation_30d), 1),
        "has_strings":            has_strings,
        # Medidor ya elegido y resuelto -- el frontend lo dibuja, no lo decide.
        "medidor":                medidor,
        "medidor_tipo":           medidor_tipo,
        "medidor_principal":      med_p,
        "medidor_respaldo":       med_r,
    }
    _cache_set(_detail_key, CACHE_TTL_DETAIL, result)
    return result


@router.get("/monitoring/{proyecto_id}/inverters-power")
def project_inverters_power(
    proyecto_id: int,
    date_from: str = Query(None, description="YYYY-MM-DD (default: hoy)"),
    date_to: str = Query(None, description="YYYY-MM-DD (default: hoy)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Potencia por inversor (serie temporal) de un proyecto, en un rango de fechas.

    Solenium devuelve `power` como dict llaveado por dev_name del inversor. Aquí lo
    normalizamos a una lista de series — una por inversor — que el front usa tanto
    para la gráfica comparativa (todas las líneas) como para la individual (al
    expandir un inversor; filtra por dev_name).

    Sin fechas → hoy (resolución 5 min). En rangos de varios días se agrupa por hora.
    """
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    if not p.project_id_solenium:
        raise HTTPException(422, "Proyecto sin ID Solenium")

    sol_id = int(p.project_id_solenium)
    today = date.today().isoformat()
    df = date_from or today
    dt = date_to or today

    client = _get_client()
    raw = client.get_power(sol_id, df, dt) or {}
    power = raw.get("power") or (raw.get("results") or {}).get("power") or {}

    multiday = df != dt
    inverters: list[dict] = []
    for dev_name, series in power.items():
        if not isinstance(series, dict):
            continue
        pts = sorted(series.items())
        if multiday:
            # Agrupar por hora: promedio de potencia por franja "YYYY-MM-DD HH"
            buckets: dict[str, list[float]] = {}
            for ts, v in pts:
                buckets.setdefault(str(ts)[:13], []).append(float(v or 0))
            points = [{"time": f"{k}:00", "kw": round(sum(vs) / len(vs), 2)}
                      for k, vs in sorted(buckets.items())]
        else:
            points = [{"time": str(ts), "kw": round(float(v or 0), 2)} for ts, v in pts]
        peak = max((pt["kw"] for pt in points), default=0.0)
        inverters.append({"dev_name": dev_name, "points": points, "peak_kw": round(peak, 2)})

    inverters.sort(key=lambda x: x["dev_name"])
    return {
        "proyecto_id":  p.id,
        "sol_id":       sol_id,
        "date_from":    df,
        "date_to":      dt,
        "granularidad": "hour" if multiday else "5min",
        "inverters":    inverters,
    }


