"""Sincronización TSF → tabla `proyectos` (operaciones).

Copia/actualiza los proyectos del pipeline de construcción de TSF hacia la tabla
real `proyectos`, para que el equipo pueda relacionarlos con contratos y monitorear
cumplimiento de energía antes de que la planta opere.

Fuente del pipeline (igual que el endpoint de lectura original):
  1. originabotdb.minifarm_project (etapa + potencia + ubicación) — fuente base.
  2. Sun Factory (sunfactory.solenium.co) → fecha de energización (hito RETIE/legalización)
     + % de avance de obra. Cruce por base_name ↔ minifarm_project.name.
  3. API de generación Unergy → ¿ya genera? Si sí, está energizada de hecho.

`sync_tsf_projects(db, force)` hace un upsert por `proyectos.origina_code`:
  - Crea el proyecto si no existe (origen='tsf_sync', estado='en_desarrollo').
  - Actualiza los campos propios de TSF (fase, % obra, potencia, fecha estimada).
  - Respeta `fecha_estimada_editada_manual` salvo `force=True` (el operador pidió
    re-sincronizar y sobrescribir sus cambios con la info de Solenium).
Todos los cruces externos son best-effort: si una fuente no responde, degrada.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
import psycopg
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger("tsf_sync")

# Etapas REALES del ciclo de vida de minifarm_project (originabotdb), de la más
# cercana a energización a la más lejana. El ciclo es:
#   signed → bt_and_contract → construction → deploy → operation
# `deploy` (PEM/pruebas) es la última etapa antes de `operation` (ya energizado).
_PIPELINE_STAGES = ["deploy", "construction", "bt_and_contract"]

# minifarm_project.stage → etiqueta de fase de construcción persistida en
# `proyectos.fase_construccion` (y consumida por el frontend).
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

# Columnas de ubicación que puede tener minifarm_project (se incluyen en el SELECT
# solo las que existan en el esquema real). Mapa: columna_origen → campo proyectos.
_LOCATION_CANDIDATES = {
    "latitude": "latitud", "lat": "latitud",
    "longitude": "longitud", "lng": "longitud", "lon": "longitud",
    "municipality": "municipio", "city": "municipio", "municipio": "municipio",
    "department": "departamento", "state": "departamento", "departamento": "departamento",
}


def _fix_url(url: str) -> str:
    """Normaliza la URL al esquema que acepta psycopg3 (`postgresql://`)."""
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
    """Estimación de respaldo de la fecha de energización (sin Sun Factory)."""
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


def _derive_commercial_name(code: str) -> str:
    """Nombre legible derivado del código de proyecto de origina.

    Los códigos tienen la forma `<PREFIJO>_<SITIO>`, p. ej.
    `COLSUCT3P1_MORROA_SUR` → "Morroa Sur". Es el respaldo cuando el proyecto aún
    no está en la tabla `proyectos`."""
    if not code:
        return ""
    parts = code.split("_", 1)
    prefix = parts[0]
    is_code_prefix = bool(re.match(r"^COL[A-Z0-9]*$", prefix)) or any(c.isdigit() for c in prefix)
    readable = (parts[1] if len(parts) > 1 and is_code_prefix else code)
    readable = readable.replace("_", " ").strip()
    return readable.title() if readable else code


# ── Ubicación: introspección del esquema de minifarm_project ────────────────────

def _location_columns(conn) -> dict[str, str]:
    """{ columna_origen: campo_proyectos } para las columnas de ubicación que
    REALMENTE existen en minifarm_project. Evita que el SELECT falle si el esquema
    de originabotdb no trae lat/lon/municipio."""
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'minifarm_project'"
        ).fetchall()
    except Exception as exc:
        logger.debug("no se pudo introspeccionar minifarm_project: %s", exc)
        return {}
    present = {r[0].lower() for r in rows}
    return {src: dst for src, dst in _LOCATION_CANDIDATES.items() if src in present}


# ── Cronogramas EPC de Sun Factory (Solenium) ───────────────────────────────────

def _sunfactory_token() -> str | None:
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
    """{ base_name.upper(): project_id } para cruzar con minifarm_project.name."""
    base = settings.SUNFACTORY_API_URL.rstrip("/")
    url: str | None = f"{base}/project/?limit=200"
    out: dict[str, int] = {}
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
        pages = 0
        while url and pages < 100:
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
    """Función PURA: elige el hito de energización de una lista de milestones."""
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
    """{ name.upper(): avg_daily_mwh } concurrente. Solo entradas con generación > 0."""
    targets = [n for n in names if n]
    if not targets:
        return {}
    out: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=min(len(targets), 12)) as pool:
        for name, avg in pool.map(lambda n: (n, _recent_avg_daily_mwh(token, n)), targets):
            if avg and avg > 0:
                out[name.upper()] = avg
    return out


# ── Sun Factory como FUENTE PRINCIPAL (la "BD de Solenium/TSF") ─────────────────
# El endpoint /project/ de Sun Factory ya trae nombre, base_name, ubicación
# (lat/lon/city/department) y estado — accesible por internet, sin depender de
# originabotdb (que solo es alcanzable desde la red interna de Unergy y hace
# timeout desde Railway/fuera). Esta es la vía que pidió el usuario: copiar
# directo desde Solenium/TSF.

# state (int) de Sun Factory → etiqueta de fase. Solo estos estados se importan
# como "próximos a energizarse"; se excluyen 2 (Operación y Mantenimiento, ya
# energizado) y 5 (Debida diligencia, demasiado temprano). Se usa el int y no la
# descripción para evitar problemas de acentos/encoding.
_SF_IMPORT_STATES = {
    1: "En construcción",      # Construcción
    3: "Próximo a energizar",  # Despliegue (PEM/pruebas, lo más cercano)
    4: "En construcción",      # BT y Contrato
}


def _sunfactory_all_projects(token: str) -> list[dict]:
    """Lista completa de proyectos de Sun Factory (paginando /project/)."""
    base = settings.SUNFACTORY_API_URL.rstrip("/")
    url: str | None = f"{base}/project/?limit=200"
    out: list[dict] = []
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as client:
        pages = 0
        while url and pages < 30:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            out += data.get("results", []) if isinstance(data, dict) else (data or [])
            url = data.get("next") if isinstance(data, dict) else None
            pages += 1
    return out


def _next_milestone_date(project: dict) -> date | None:
    """Fecha del próximo hito pendiente (respaldo cuando no se enriquece con
    el hito de energización RETIE/legalización)."""
    nm = project.get("next_milestone") or {}
    return _parse_iso_date(nm.get("planned_end_date") or nm.get("end_date")
                           or nm.get("planned_date") or nm.get("date"))


def fetch_sunfactory_projects(enrich_dates: bool = True) -> tuple[list[dict], list[str]]:
    """Proyectos del pipeline DIRECTO desde Sun Factory (Solenium/TSF).

    Devuelve `(proyectos, warnings)`. Cada proyecto:
    `{ origina_code, solenium_id, commercial_name, status, municipio,
       departamento, latitud, longitud, energization_date, avance_pct,
       monthly_mwh }`. `origina_code` = base_name (o `SF-<id>` si no tiene),
    usado como llave estable de upsert."""
    warnings: list[str] = []
    try:
        token = _sunfactory_token()
    except Exception as exc:
        logger.warning("Sun Factory auth falló: %s", exc)
        return [], [f"No se pudo autenticar contra Sun Factory: {exc}"]
    if not token:
        return [], ["Credenciales de Sun Factory no configuradas (SUNFACTORY_/SOLENIUM_)."]

    try:
        raw = _sunfactory_all_projects(token)
    except Exception as exc:
        logger.warning("Sun Factory lista de proyectos falló: %s", exc)
        return [], [f"No se pudo leer la lista de proyectos de Sun Factory: {exc}"]

    wanted = [p for p in raw if p.get("state") in _SF_IMPORT_STATES]

    # Enriquecer con el hito de energización (RETIE/legalización) por proyecto,
    # concurrente y best-effort. Si falla, se usa el next_milestone como respaldo.
    energ_map: dict[int, dict] = {}
    if enrich_dates and wanted:
        ids = [p["id"] for p in wanted if p.get("id") is not None]
        try:
            with ThreadPoolExecutor(max_workers=min(len(ids), 12)) as pool:
                for pid, energ in pool.map(lambda i: (i, _sunfactory_energization(token, i)), ids):
                    if energ:
                        energ_map[pid] = energ
        except Exception as exc:
            logger.warning("Sun Factory enriquecimiento de hitos falló: %s", exc)
            warnings.append("No se pudieron leer los hitos de energización; se usan fechas tentativas.")

    projects: list[dict] = []
    for p in wanted:
        pid = p.get("id")
        base_name = p.get("base_name")
        code = base_name or (f"SF-{pid}" if pid is not None else None)
        if not code:
            continue
        energ_info = energ_map.get(pid) or {}
        energ = energ_info.get("energization_date") or _next_milestone_date(p)
        lat = p.get("lat")
        lon = p.get("lon")
        projects.append({
            "origina_code": code,
            "solenium_id": pid,
            "commercial_name": p.get("name") or _derive_commercial_name(base_name or ""),
            "status": _SF_IMPORT_STATES.get(p.get("state"), "En construcción"),
            "municipio": p.get("city"),
            "departamento": p.get("department"),
            "latitud": float(lat) if lat not in (None, "") else None,
            "longitud": float(lon) if lon not in (None, "") else None,
            "energization_date": energ,
            "avance_pct": energ_info.get("avance_pct"),
            "monthly_mwh": None,  # Sun Factory no expone potencia en el listado
        })
    return projects, warnings


# ── Pipeline enriquecido (originabotdb, opcional/legacy) ─────────────────────────

def fetch_pipeline_projects(
    *,
    cross_sunfactory: bool = True,
    cross_generacion: bool = True,
    yield_kwh_kwp_day: float = _DEFAULT_YIELD_KWH_KWP_DAY,
) -> tuple[list[dict], list[str]]:
    """Lee el pipeline de originabotdb y lo enriquece con Sun Factory + generación
    Unergy. Devuelve `(proyectos, warnings)`. Cada proyecto es un dict normalizado:
    `{ origina_code, commercial_name, status, stage, energization_date,
       energization_source, avance_pct, monthly_mwh, installed_power_kwp,
       already_generating, municipio, departamento, latitud, longitud }`."""
    warnings: list[str] = []
    with _oconn() as conn:
        if conn is None:
            return [], ["ORIGINA_DATABASE_URL no configurada — pipeline no disponible."]

        loc_cols = _location_columns(conn)
        loc_select = "".join(f", p.{src} AS loc_{src}" for src in loc_cols)
        try:
            cur = conn.execute(
                f"""
                SELECT p.id, p.name, p.stage,
                       p.project_installed_power, p.project_dc_capacity, p.contract_type,
                       sc.last_stage_date{loc_select}
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
            )
            col_names = [d.name for d in cur.description]
            rows = cur.fetchall()
        except Exception as exc:
            logger.warning("originabotdb pipeline query failed: %s", exc)
            return [], ["No se pudo leer el pipeline desde originabotdb — revisar conexión/credenciales."]

    names = [r[1] for r in rows]

    # Sun Factory: fecha de energización real + % avance (prioritario).
    sf_map: dict[str, dict] = {}
    if cross_sunfactory:
        try:
            sf_token = _sunfactory_token()
            if sf_token:
                sf_map = _build_sunfactory_map(sf_token, names)
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
                gen_map = _build_generation_map(gen_token, names)
            else:
                warnings.append("Credenciales de generación Unergy no configuradas — proyección teórica.")
        except Exception as exc:
            logger.warning("Unergy generation auth/sync failed: %s", exc)
            warnings.append("API de generación Unergy no disponible — proyección teórica.")

    projects: list[dict] = []
    for r in rows:
        row = dict(zip(col_names, r))
        name = row["name"]
        stage = row["stage"]
        installed_power = row["project_installed_power"]

        status = _STAGE_TO_STATUS.get(stage, "En construcción")
        monthly = _project_monthly_mwh(installed_power, yield_kwh_kwp_day)
        avance_pct = None

        sf = sf_map.get(name.upper()) if name else None
        if sf and sf.get("energization_date"):
            energ = sf["energization_date"]
            energ_source = "sunfactory"
            avance_pct = sf.get("avance_pct")
        else:
            energ = _estimate_energization(stage, row.get("last_stage_date"))
            energ_source = "estimado" if energ else "desconocido"

        already_generating = False
        avg = gen_map.get(name.upper()) if name else None
        if avg and avg > 0:
            already_generating = True
            monthly = round(avg * 30, 2)
            if status != "Energizado":
                status = "Próximo a energizar"

        # Ubicación: toma las columnas que existieran en minifarm_project.
        loc: dict[str, object] = {"municipio": None, "departamento": None,
                                  "latitud": None, "longitud": None}
        for src, dst in loc_cols.items():
            val = row.get(f"loc_{src}")
            if val not in (None, "") and loc.get(dst) is None:
                loc[dst] = val

        projects.append({
            "origina_code": name,
            "commercial_name": _derive_commercial_name(name),
            "status": status,
            "stage": stage,
            "energization_date": energ,
            "energization_source": energ_source,
            "avance_pct": avance_pct,
            "monthly_mwh": monthly,
            "installed_power_kwp": installed_power,
            "already_generating": already_generating,
            **loc,
        })

    return projects, warnings


# ── Upsert en `proyectos` ───────────────────────────────────────────────────────

# Fase de construcción persistida (slug) ↔ etiqueta del pipeline.
_STATUS_TO_FASE = {
    "En construcción": "en_construccion",
    "Pruebas": "pruebas",
    "Próximo a energizar": "proximo_energizar",
    "Energizado": "energizado",
}
# Inverso: slug → etiqueta que consume el frontend.
_FASE_TO_LABEL = {v: k for k, v in _STATUS_TO_FASE.items()}


def sync_tsf_projects(db: Session, force: bool = False) -> dict:
    """Upsert del pipeline TSF en `proyectos`. Devuelve estadísticas.

    `force=True`: sobrescribe la fecha estimada incluso si el operador la editó
    manualmente, y resetea la marca (Solenium suele tener la fecha más fresca).

    Fuente principal: Sun Factory (la "BD de Solenium/TSF"), accesible por internet.
    No depende de originabotdb (que solo es alcanzable desde la red interna)."""
    projects, warnings = fetch_sunfactory_projects()
    stats = {"creados": 0, "actualizados": 0, "sin_cambios": 0, "errores": 0,
             "total_pipeline": len(projects), "warnings": warnings, "fuente": "sunfactory"}

    for p in projects:
        code = p["origina_code"]
        if not code:
            continue
        try:
            existing = db.execute(
                text("SELECT id, fecha_estimada_editada_manual FROM proyectos "
                     "WHERE origina_code = :code AND deleted_at IS NULL"),
                {"code": code},
            ).first()

            fase = _STATUS_TO_FASE.get(p["status"], "en_construccion")
            energ = p["energization_date"]

            if existing is None:
                db.execute(
                    text("""
                        INSERT INTO proyectos (
                            nombre_comercial, origina_code, fase_construccion,
                            fecha_estimada_energizacion, fecha_estimada_editada_manual,
                            avance_obra_pct, mwh_mes_estimado, potencia_instalada_kwp,
                            municipio, departamento, latitud, longitud,
                            estado, tipo_proyecto, origen,
                            created_at, updated_at
                        ) VALUES (
                            :nombre, :code, :fase,
                            :energ, FALSE,
                            :avance, :mwh, :potencia,
                            :municipio, :departamento, :latitud, :longitud,
                            'en_desarrollo', 'minigranja', 'tsf_sync',
                            NOW(), NOW()
                        )
                    """),
                    {
                        "nombre": p["commercial_name"] or code,
                        "code": code,
                        "fase": fase,
                        "energ": energ,
                        "avance": p.get("avance_pct"),
                        "mwh": p.get("monthly_mwh"),
                        "potencia": p.get("installed_power_kwp"),
                        "municipio": p["municipio"],
                        "departamento": p["departamento"],
                        "latitud": p["latitud"],
                        "longitud": p["longitud"],
                    },
                )
                stats["creados"] += 1
            else:
                manual = bool(existing.fecha_estimada_editada_manual)
                # La fecha estimada solo se pisa si no la editó el operador, o si force.
                set_date = (not manual) or force
                params = {
                    "id": existing.id,
                    "fase": fase,
                    "avance": p.get("avance_pct"),
                    "potencia": p.get("installed_power_kwp"),
                }
                date_sql = ""
                if set_date and energ is not None:
                    date_sql = (", fecha_estimada_energizacion = :energ, "
                                "fecha_estimada_editada_manual = FALSE")
                    params["energ"] = energ
                db.execute(
                    text(f"""
                        UPDATE proyectos SET
                            fase_construccion = :fase,
                            avance_obra_pct = COALESCE(:avance, avance_obra_pct),
                            potencia_instalada_kwp = COALESCE(:potencia, potencia_instalada_kwp){date_sql},
                            updated_at = NOW()
                        WHERE id = :id
                    """),
                    params,
                )
                stats["actualizados"] += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("upsert TSF falló para %s: %s", code, exc)
            stats["errores"] += 1

    return stats
