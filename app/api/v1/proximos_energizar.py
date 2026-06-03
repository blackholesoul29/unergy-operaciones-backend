"""
Proyectos próximos a energizarse — pipeline real desde originabotdb, cruzado con
los cronogramas EPC de Sun Factory (fecha de energización + % de avance de obra)
y con la API de generación de Unergy (detección de plantas ya generando).

Reemplaza el MVP del frontend que vivía en localStorage (entrada manual).

Cruces de datos (en orden de prioridad para la fecha de energización):
  1. Sun Factory (sunfactory.solenium.co) → hito de energización (RETIE/legalización):
     `date` proyectada + `progress.calculated_percentage`. Cruce por `base_name`
     ↔ minifarm_project.name. [PRIORIDAD para fecha y avance]
  2. originabotdb minifarm_projectstagechange.review_date → estimación de respaldo.
  3. API de generación Unergy (api.unergy.io) → ¿la planta ya genera? Si sí, está
     energizada de hecho y usamos su promedio real para MWh/mes.

`minifarm_project` (originabotdb) es siempre la fuente del pipeline + potencia.
Todos los cruces externos son best-effort: si una fuente no responde, el endpoint
degrada con elegancia a la mejor información disponible.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
import psycopg
from fastapi import APIRouter, Depends, Query

from app.api.v1.auth import get_current_user
from app.core.config import settings

logger = logging.getLogger("proximos_energizar")
router = APIRouter(prefix="/proximos-energizar", tags=["Próximos a energizarse"])

# Etapas del pipeline de originabotdb que cuentan como "próximo a energizarse",
# ordenadas de la MÁS cercana a energización a la más lejana.
_PIPELINE_STAGES = ["uci", "deploy", "construction", "bt_and_contract"]

# minifarm_project.stage → etiqueta de estado que consume el frontend.
_STAGE_TO_STATUS = {
    "uci": "Próximo a energizar",
    "deploy": "Pruebas",
    "construction": "En construcción",
    "bt_and_contract": "En construcción",
    "operation": "Energizado",
}

# Cuando no hay fecha de Sun Factory ni `review_date`, estimamos sumando estos días
# a la fecha del último cambio de etapa. Refleja el tiempo típico restante por etapa.
_STAGE_OFFSET_DAYS = {
    "uci": 15, "deploy": 30, "construction": 90, "bt_and_contract": 150, "operation": 0,
}

# Rendimiento específico para proyectar MWh/mes desde la potencia instalada.
# Caribe colombiano (Cesar, Magdalena, Bolívar…) ronda 4.3–4.8 kWh/kWp/día.
_DEFAULT_YIELD_KWH_KWP_DAY = 4.3

# El hito de energización en los cronogramas Sun Factory: RETIE/legalización/PEM.
_ENERG_MILESTONE_RE = re.compile(r"retie|legaliz|energiz|puesta\s+en\s+marcha|\bpem\b|\bpdm\b", re.I)


def _fix_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


@contextmanager
def _oconn():
    """Conexión read-only a originabotdb (mismo patrón que mapa.py)."""
    if not settings.ORIGINA_DATABASE_URL:
        yield None
        return
    conn = psycopg.connect(_fix_url(settings.ORIGINA_DATABASE_URL), autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def _estimate_energization(stage: str, review_date, last_stage_date) -> date | None:
    """Estimación de respaldo de la fecha de energización (sin Sun Factory)."""
    if review_date:
        return review_date if isinstance(review_date, date) else review_date.date()
    if last_stage_date:
        base = last_stage_date.date() if isinstance(last_stage_date, datetime) else last_stage_date
        return base + timedelta(days=_STAGE_OFFSET_DAYS.get(stage, 60))
    return None


def _project_monthly_mwh(installed_power_kwp: float | None, yield_kwh_kwp_day: float) -> float | None:
    if not installed_power_kwp or installed_power_kwp <= 0:
        return None
    return round(installed_power_kwp * yield_kwh_kwp_day * 30 / 1000, 2)


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return None


# ── Cronogramas EPC de Sun Factory (Solenium) ───────────────────────────────────

def _sunfactory_token() -> str | None:
    if not (settings.SUNFACTORY_USERNAME and settings.SUNFACTORY_PASSWORD and settings.SUNFACTORY_AUTH_URL):
        return None
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            settings.SUNFACTORY_AUTH_URL,
            json={"username": settings.SUNFACTORY_USERNAME, "password": settings.SUNFACTORY_PASSWORD},
        )
        resp.raise_for_status()
        return resp.json()["access"]


def _sunfactory_project_map(token: str) -> dict[str, int]:
    """{ base_name.upper(): project_id } para cruzar con minifarm_project.name.

    El API capa `page_size` a 10 (ignora `limit`), así que hay que seguir la
    paginación `next` hasta agotarla — son ~200 proyectos / ~20 páginas.
    """
    base = settings.SUNFACTORY_API_URL.rstrip("/")
    url: str | None = f"{base}/project/?limit=200"
    out: dict[str, int] = {}
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
        pages = 0
        while url and pages < 100:  # tope de seguridad
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("results", []) if isinstance(data, dict) else (data or [])
            for p in rows:
                if p.get("base_name"):
                    out[p["base_name"].upper()] = p["id"]
            url = data.get("next") if isinstance(data, dict) else None
            pages += 1
    return out


def _sunfactory_energization(token: str, project_id: int) -> dict | None:
    """Hito de energización (RETIE/legalización) de un proyecto: fecha + % avance.

    Devuelve { energization_date, avance_pct, milestone } o None.
    """
    base = settings.SUNFACTORY_API_URL.rstrip("/")
    try:
        with httpx.Client(timeout=40) as client:
            resp = client.get(f"{base}/project/{project_id}/milestones/",
                             headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.debug("Sun Factory milestones failed for project %s: %s", project_id, exc)
        return None

    milestones = data.get("results", data) if isinstance(data, dict) else data
    dated = [m for m in milestones if m.get("date") or m.get("planned_date")]
    if not dated:
        return None
    # Prioriza el hito de energización por nombre; si no hay, usa el hito final.
    matches = [m for m in dated if _ENERG_MILESTONE_RE.search(m.get("name", ""))]
    pool = matches or dated
    chosen = max(pool, key=lambda m: m.get("planned_date") or m.get("date") or "")

    ed = _parse_iso_date(chosen.get("date") or chosen.get("planned_date"))
    if not ed:
        return None
    progress = chosen.get("progress") or {}
    avance = progress.get("calculated_percentage")
    if avance is None:
        avance = progress.get("activity_percentage")
    return {"energization_date": ed, "avance_pct": avance, "milestone": chosen.get("name")}


def _build_sunfactory_map(token: str, base_names: list[str]) -> dict[str, dict]:
    """{ base_name.upper(): energización } para los proyectos del pipeline, concurrente."""
    try:
        proj_map = _sunfactory_project_map(token)
    except Exception as exc:
        logger.warning("Sun Factory project list failed: %s", exc)
        return {}

    wanted = {bn.upper(): proj_map[bn.upper()] for bn in base_names if bn and bn.upper() in proj_map}
    if not wanted:
        return {}

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(len(wanted), 12)) as pool:
        results = pool.map(lambda kv: (kv[0], _sunfactory_energization(token, kv[1])), wanted.items())
        for bn, energ in results:
            if energ:
                out[bn] = energ
    return out


# ── Cruce con la API de generación de Unergy (api.unergy.io) ────────────────────

def _unergy_token() -> str | None:
    if not (settings.UNERGY_ACCOUNT_ID and settings.UNERGY_LOGIN and settings.UNERGY_PASSWORD):
        return None
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/",
            json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD},
            headers={"User-Agent": "PostmanRuntime/7.50.0"},
        )
        resp.raise_for_status()
        return resp.json()["access"]


def _recent_avg_daily_mwh(token: str, sub_project: str, n_days_window: int = 30) -> float | None:
    """Promedio diario real (MWh) de la API de generación de Unergy. >0 ⇒ ya genera."""
    now_col = datetime.now(timezone.utc) - timedelta(hours=5)
    start_utc = (now_col - timedelta(days=n_days_window)) + timedelta(hours=5)
    end_utc = now_col + timedelta(hours=5)
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/",
                params={
                    "time_stamp__gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                    "limit": "10000",
                },
                headers={"Authorization": f"Bearer {token}", "User-Agent": "PostmanRuntime/7.50.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.debug("Unergy generation cross-check failed for %s: %s", sub_project, exc)
        return None

    if not records:
        return None
    records_sorted = sorted(records, key=lambda r: r.get("time_stamp", ""))
    diff_kwh = (records_sorted[-1].get("generacion") or 0) - (records_sorted[0].get("generacion") or 0)
    if diff_kwh <= 0:
        return None
    return round((diff_kwh / 1000) / n_days_window, 4)


@router.get("")
def proximos_energizar(
    cross_sunfactory: bool = Query(True, description="Cruzar con cronogramas Sun Factory para fecha de energización real + % de avance."),
    cross_generacion: bool = Query(True, description="Cruzar con la API de generación de Unergy para detectar plantas ya energizadas."),
    yield_kwh_kwp_day: float = Query(_DEFAULT_YIELD_KWH_KWP_DAY, ge=1.0, le=8.0, description="Rendimiento específico para la proyección de MWh/mes."),
    _=Depends(get_current_user),
) -> dict:
    """Proyectos en pipeline de construcción con su proyección de generación.

    Forma de cada proyecto (compatible con el frontend):
    `{ id, name, status, energizationDate, contracts, monthlyMwh, avancePct, ... }`.
    """
    with _oconn() as conn:
        if conn is None:
            return {"projects": [], "source": "unavailable",
                    "warning": "ORIGINA_DATABASE_URL no configurada — pipeline no disponible."}
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.stage,
                   p.project_installed_power, p.project_dc_capacity, p.contract_type,
                   sc.last_stage_date, sc.review_date
            FROM minifarm_project p
            LEFT JOIN LATERAL (
                SELECT created_at AS last_stage_date, review_date
                FROM minifarm_projectstagechange c
                WHERE c.project_id = p.id
                ORDER BY created_at DESC
                LIMIT 1
            ) sc ON TRUE
            WHERE p.stage = ANY(%s)
            ORDER BY array_position(%s::text[], p.stage), sc.review_date NULLS LAST
            """,
            (_PIPELINE_STAGES, _PIPELINE_STAGES),
        ).fetchall()

    warnings = []

    # Sun Factory: fecha de energización real + % avance (prioritario).
    sf_map: dict[str, dict] = {}
    if cross_sunfactory:
        try:
            sf_token = _sunfactory_token()
            if sf_token:
                sf_map = _build_sunfactory_map(sf_token, [r[1] for r in rows])
            else:
                warnings.append("Credenciales de Sun Factory no configuradas — fecha de energización estimada.")
        except Exception as exc:
            logger.warning("Sun Factory auth/sync failed: %s", exc)
            warnings.append("Sun Factory no disponible — fecha de energización estimada.")

    # Generación Unergy: ¿ya está generando?
    gen_token = None
    if cross_generacion:
        try:
            gen_token = _unergy_token()
            if gen_token is None:
                warnings.append("Credenciales de generación Unergy no configuradas — proyección teórica.")
        except Exception as exc:
            logger.warning("Unergy generation auth failed: %s", exc)
            warnings.append("API de generación Unergy no disponible — proyección teórica.")

    projects = []
    for r in rows:
        (pid, name, stage, installed_power, dc_capacity, contract_type,
         last_stage_date, review_date) = r

        status = _STAGE_TO_STATUS.get(stage, "En construcción")
        monthly = _project_monthly_mwh(installed_power, yield_kwh_kwp_day)
        projection_basis = "potencia_instalada"
        already_generating = False
        avance_pct = None

        # Fecha de energización: Sun Factory tiene prioridad sobre la estimación.
        sf = sf_map.get(name.upper()) if name else None
        if sf and sf.get("energization_date"):
            energ = sf["energization_date"]
            energ_source = "sunfactory"
            avance_pct = sf.get("avance_pct")
        else:
            energ = _estimate_energization(stage, review_date, last_stage_date)
            energ_source = "review_date" if review_date else ("estimado" if energ else "desconocido")

        # ¿Ya genera? → energizada de hecho + promedio real.
        if gen_token and name:
            avg = _recent_avg_daily_mwh(gen_token, name)
            if avg and avg > 0:
                already_generating = True
                monthly = round(avg * 30, 2)
                projection_basis = "generacion_real_unergy"
                if status != "Energizado":
                    status = "Próximo a energizar"

        projects.append({
            "id": pid,
            "name": name,
            "status": status,
            "stage": stage,
            "energizationDate": energ.isoformat() if energ else None,
            "energizationSource": energ_source,
            "avancePct": avance_pct,
            "contracts": [],
            "monthlyMwh": monthly,
            "installedPowerKwp": installed_power,
            "dcCapacityKwp": dc_capacity,
            "contractType": contract_type,
            "alreadyGenerating": already_generating,
            "projectionBasis": projection_basis,
        })

    result = {"projects": projects, "source": "originabotdb", "count": len(projects),
              "yieldKwhKwpDay": yield_kwh_kwp_day,
              "sunfactoryMatched": len(sf_map)}
    if warnings:
        result["warning"] = " ".join(warnings)
    return result
