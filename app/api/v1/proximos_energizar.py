"""
Proyectos próximos a energizarse — pipeline real desde originabotdb, cruzado con
los cronogramas EPC de Sun Factory (fecha de energización + % de avance de obra)
y con la API de generación de Unergy (detección de plantas ya generando).

Reemplaza el MVP del frontend que vivía en localStorage (entrada manual).

Cruces de datos (en orden de prioridad para la fecha de energización):
  1. Sun Factory (sunfactory.solenium.co) → hito de energización (RETIE/legalización):
     `date` proyectada + `progress.calculated_percentage`. Cruce por `base_name`
     ↔ minifarm_project.name. [PRIORIDAD para fecha y avance]
  2. originabotdb minifarm_projectstagechange.created_at + offset por etapa → estimación de respaldo.
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
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db

logger = logging.getLogger("proximos_energizar")
router = APIRouter(prefix="/proximos-energizar", tags=["Próximos a energizarse"])

# Etapas REALES del ciclo de vida de minifarm_project (originabotdb), de la más
# cercana a energización a la más lejana. El ciclo es:
#   signed → bt_and_contract → construction → deploy → operation
# `deploy` (PEM/pruebas) es la última etapa antes de `operation` (ya energizado),
# así que es la más cercana a energizarse. NO existe ninguna etapa "uci".
_PIPELINE_STAGES = ["deploy", "construction", "bt_and_contract"]

# minifarm_project.stage → etiqueta de estado que consume el frontend.
# Las etiquetas deben pertenecer a STATUS_OPTIONS del componente Vue
# (ProyectosProximosEnergizar.vue): "En construcción"/"Pruebas"/"Próximo a energizar"/"Energizado".
_STAGE_TO_STATUS = {
    "deploy": "Próximo a energizar",
    "construction": "En construcción",
    "bt_and_contract": "En construcción",
    "operation": "Energizado",
}

# Cuando no hay fecha de Sun Factory, estimamos sumando estos días a la fecha del
# último cambio de etapa. Refleja el tiempo típico restante por etapa.
_STAGE_OFFSET_DAYS = {
    "deploy": 30, "construction": 90, "bt_and_contract": 150, "operation": 0,
}

# Rendimiento específico para proyectar MWh/mes desde la potencia instalada.
# Caribe colombiano (Cesar, Magdalena, Bolívar…) ronda 4.3–4.8 kWh/kWp/día.
_DEFAULT_YIELD_KWH_KWP_DAY = 4.3

# El hito de energización en los cronogramas Sun Factory: RETIE/legalización/PEM.
_ENERG_MILESTONE_RE = re.compile(r"retie|legaliz|energiz|puesta\s+en\s+marcha|\bpem\b|\bpdm\b", re.I)


def _fix_url(url: str) -> str:
    """Normaliza la URL al esquema que acepta psycopg3 (`postgresql://`).

    Contempla el esquema de driver de SQLAlchemy (`postgresql+psycopg://`) y el
    `postgres://` que emiten Railway/Heroku para DATABASE_URL — psycopg3 rechaza
    este último, así que una URL de Railway sin normalizar fallaría al conectar.
    """
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
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


def _estimate_energization(stage: str, last_stage_date) -> date | None:
    """Estimación de respaldo de la fecha de energización (sin Sun Factory):
    fecha del último cambio de etapa + offset típico restante por etapa."""
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


# ── Nombre comercial (BD de operaciones + respaldo derivado del código) ─────────

def _derive_commercial_name(code: str) -> str:
    """Nombre legible derivado del código de proyecto de origina.

    Los códigos tienen la forma `<PREFIJO>_<SITIO>`, p. ej.
    `COLSUCT3P1_MORROA_SUR` → "Morroa Sur". El prefijo de origina empieza por
    `COL` o contiene dígitos (p. ej. `COLSUCT3P1`); solo se descarta si lo parece,
    así nombres como `MORROSQUILLO_2` se conservan completos ("Morrosquillo 2").
    Es el respaldo cuando el proyecto aún no está en la tabla `proyectos` (típico
    en el pipeline pre-operación)."""
    if not code:
        return ""
    parts = code.split("_", 1)
    prefix = parts[0]
    is_code_prefix = bool(re.match(r"^COL[A-Z0-9]*$", prefix)) or any(c.isdigit() for c in prefix)
    readable = (parts[1] if len(parts) > 1 and is_code_prefix else code)
    readable = readable.replace("_", " ").strip()
    return readable.title() if readable else code


def _commercial_name_map(db: Session) -> dict[str, str]:
    """{ origina_code.upper(): nombre_comercial } desde la BD de operaciones.

    Permite mostrar el nombre comercial REAL cuando el proyecto del pipeline ya
    existe en `proyectos` (correlacionado vía origina_code). Best-effort: si la
    consulta falla, se cae al nombre derivado del código."""
    try:
        rows = db.execute(text(
            "SELECT origina_code, nombre_comercial FROM proyectos "
            "WHERE origina_code IS NOT NULL AND nombre_comercial IS NOT NULL"
        )).all()
        return {code.upper(): nombre for code, nombre in rows if code and nombre}
    except Exception as exc:
        logger.warning("commercial name map query failed: %s", exc)
        return {}


# ── Cronogramas EPC de Sun Factory (Solenium) ───────────────────────────────────

def _sunfactory_token() -> str | None:
    # Sun Factory authenticates against auth.solenium.co — the SAME IdP as the rest of
    # the Solenium integration (solenium_client, monitoreo). Reuse the existing
    # SOLENIUM_USER/SOLENIUM_PASS creds so prod needs NO new secrets; SUNFACTORY_* win
    # if set, for the day Sun Factory ever gets a dedicated account.
    user = settings.SUNFACTORY_USERNAME or settings.SOLENIUM_USER
    password = settings.SUNFACTORY_PASSWORD or settings.SOLENIUM_PASS
    if not (user and password and settings.SUNFACTORY_AUTH_URL):
        return None
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            settings.SUNFACTORY_AUTH_URL,
            json={"username": user, "password": password},
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


def _pick_energization_milestone(milestones: list[dict]) -> dict | None:
    """Función PURA: elige el hito de energización de una lista de milestones.

    Prioriza por nombre (RETIE/legalización/energización); si ninguno coincide,
    usa el hito final (mayor fecha planeada). Devuelve
    { energization_date, avance_pct, milestone } o None. Sin I/O — testeable.
    """
    if not milestones:
        return None
    dated = [m for m in milestones if m.get("date") or m.get("planned_date")]
    if not dated:
        return None
    matches = [m for m in dated if _ENERG_MILESTONE_RE.search(m.get("name", "") or "")]
    pool = matches or dated
    chosen = max(pool, key=lambda m: (m.get("planned_date") or m.get("date") or ""))

    ed = _parse_iso_date(chosen.get("date") or chosen.get("planned_date"))
    if not ed:
        return None
    progress = chosen.get("progress") or {}
    avance = progress.get("calculated_percentage")
    if avance is None:
        avance = progress.get("activity_percentage")
    return {"energization_date": ed, "avance_pct": avance, "milestone": chosen.get("name")}


def _sunfactory_energization(token: str, project_id: int) -> dict | None:
    """Hito de energización de un proyecto vía Sun Factory (con paginación)."""
    base = settings.SUNFACTORY_API_URL.rstrip("/")
    milestones: list[dict] = []
    url: str | None = f"{base}/project/{project_id}/milestones/?limit=200"
    try:
        with httpx.Client(timeout=40, headers={"Authorization": f"Bearer {token}"}) as client:
            pages = 0
            while url and pages < 20:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                milestones += data.get("results", []) if isinstance(data, dict) else (data or [])
                url = data.get("next") if isinstance(data, dict) else None
                pages += 1
    except Exception as exc:
        logger.debug("Sun Factory milestones failed for project %s: %s", project_id, exc)
        return None
    return _pick_energization_milestone(milestones)


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


def _build_generation_map(token: str, names: list[str]) -> dict[str, float]:
    """{ name.upper(): avg_daily_mwh } concurrente. Solo entradas con generación > 0.

    Concurrente para no serializar ~N llamadas HTTP (cada una ~1-2s) dentro del
    request — secuencialmente provocaría timeouts.
    """
    targets = [n for n in names if n]
    if not targets:
        return {}
    out: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=min(len(targets), 12)) as pool:
        for name, avg in pool.map(lambda n: (n, _recent_avg_daily_mwh(token, n)), targets):
            if avg and avg > 0:
                out[name.upper()] = avg
    return out


@router.get("")
def proximos_energizar(
    cross_sunfactory: bool = Query(True, description="Cruzar con cronogramas Sun Factory para fecha de energización real + % de avance."),
    cross_generacion: bool = Query(True, description="Cruzar con la API de generación de Unergy para detectar plantas ya energizadas."),
    yield_kwh_kwp_day: float = Query(_DEFAULT_YIELD_KWH_KWP_DAY, ge=1.0, le=8.0, description="Rendimiento específico para la proyección de MWh/mes."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Proyectos en pipeline de construcción con su proyección de generación.

    Forma de cada proyecto (compatible con el frontend):
    `{ id, name, commercialName, status, energizationDate, contracts, monthlyMwh, avancePct, ... }`.
    `name` es el código de origina (p. ej. COLSUCT3P1_MORROA_SUR) y `commercialName`
    el nombre comercial (real desde `proyectos`, o derivado del código)."""
    try:
        with _oconn() as conn:
            if conn is None:
                return {"projects": [], "source": "unavailable",
                        "warning": "ORIGINA_DATABASE_URL no configurada — pipeline no disponible."}
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.stage,
                       p.project_installed_power, p.project_dc_capacity, p.contract_type,
                       sc.last_stage_date
                FROM minifarm_project p
                LEFT JOIN LATERAL (
                    SELECT c.created_at AS last_stage_date
                    FROM minifarm_projectstagechange c
                    WHERE c.project_id = p.id
                    ORDER BY c.created_at DESC
                    LIMIT 1
                ) sc ON TRUE
                WHERE p.stage = ANY(%s)
                ORDER BY array_position(%s::text[], p.stage), sc.last_stage_date DESC NULLS LAST
                """,
                (_PIPELINE_STAGES, _PIPELINE_STAGES),
            ).fetchall()
    except Exception as exc:
        # No tumbar la vista por un fallo de conexión/esquema: degradar con elegancia
        # igual que cuando faltan las credenciales (el frontend muestra el aviso).
        logger.warning("originabotdb pipeline query failed: %s", exc)
        return {"projects": [], "source": "error",
                "warning": "No se pudo leer el pipeline desde originabotdb — revisar "
                           "conexión/credenciales o el esquema de minifarm_projectstagechange."}

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

    # Generación Unergy: ¿ya está generando? (concurrente)
    gen_map: dict[str, float] = {}
    if cross_generacion:
        try:
            gen_token = _unergy_token()
            if gen_token:
                gen_map = _build_generation_map(gen_token, [r[1] for r in rows])
            else:
                warnings.append("Credenciales de generación Unergy no configuradas — proyección teórica.")
        except Exception as exc:
            logger.warning("Unergy generation auth/sync failed: %s", exc)
            warnings.append("API de generación Unergy no disponible — proyección teórica.")

    # Nombre comercial: real desde la BD de operaciones (cruce por origina_code);
    # si el proyecto aún no existe ahí, se deriva del código.
    comm_map = _commercial_name_map(db)

    projects = []
    for r in rows:
        (pid, name, stage, installed_power, dc_capacity, contract_type,
         last_stage_date) = r

        commercial_name = (comm_map.get(name.upper()) if name else None) or _derive_commercial_name(name)
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
            energ = _estimate_energization(stage, last_stage_date)
            energ_source = "estimado" if energ else "desconocido"

        # ¿Ya genera? → energizada de hecho + promedio real.
        avg = gen_map.get(name.upper()) if name else None
        if avg and avg > 0:
            already_generating = True
            monthly = round(avg * 30, 2)
            projection_basis = "generacion_real_unergy"
            if status != "Energizado":
                status = "Próximo a energizar"

        projects.append({
            "id": pid,
            "name": name,
            "commercialName": commercial_name,
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
