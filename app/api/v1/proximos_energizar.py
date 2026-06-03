"""
Proyectos próximos a energizarse — pipeline real desde originabotdb, cruzado con
la API de generación de Unergy (api.unergy.io) para detectar plantas ya generando.

Reemplaza el MVP del frontend que vivía en localStorage (entrada manual). La
fuente de verdad del pipeline de construcción es `minifarm_project` en
originabotdb; la fecha de energización se deriva de `minifarm_projectstagechange`
(transiciones de etapa con su `review_date`).

Cruces de datos:
  • originabotdb (minifarm_project)        → pipeline, etapa, potencia. [FUENTE PRINCIPAL]
  • API de generación Unergy (api.unergy.io) → ¿la planta ya genera? Si sí, está
    energizada de hecho y usamos su promedio real. [best-effort, degradación elegante]
  • TODO: Sun Factory (Solenium EPC)         → cronograma: avance de obra / fecha de
    energización real. Bloqueado: cuenta sin proyectos asociados — ver
    `_fetch_sunfactory_cronograma`.

Si una fuente no está disponible, el endpoint sigue devolviendo el pipeline de
originabotdb con la proyección teórica desde la potencia instalada.
"""
from __future__ import annotations

import logging
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

# Cuando no hay `review_date`, estimamos la energización sumando estos días a la
# fecha del último cambio de etapa. Refleja el tiempo típico restante por etapa.
_STAGE_OFFSET_DAYS = {
    "uci": 15,
    "deploy": 30,
    "construction": 90,
    "bt_and_contract": 150,
    "operation": 0,
}

# Rendimiento específico para proyectar MWh/mes desde la potencia instalada.
# Caribe colombiano (Cesar, Magdalena, Bolívar…) ronda 4.3–4.8 kWh/kWp/día;
# usamos un valor conservador y lo dejamos sobre-escribible por query param.
_DEFAULT_YIELD_KWH_KWP_DAY = 4.3


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
    """Mejor estimación de la fecha de energización para un proyecto del pipeline."""
    if review_date:
        return review_date if isinstance(review_date, date) else review_date.date()
    if last_stage_date:
        base = last_stage_date.date() if isinstance(last_stage_date, datetime) else last_stage_date
        return base + timedelta(days=_STAGE_OFFSET_DAYS.get(stage, 60))
    return None


def _project_monthly_mwh(installed_power_kwp: float | None, yield_kwh_kwp_day: float) -> float | None:
    """Proyección teórica de MWh/mes a partir de la potencia instalada (kWp)."""
    if not installed_power_kwp or installed_power_kwp <= 0:
        return None
    return round(installed_power_kwp * yield_kwh_kwp_day * 30 / 1000, 2)


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
    """Promedio diario real (MWh) de la API de generación de Unergy en la ventana reciente.

    Si devuelve un valor > 0, la planta YA está generando (energizada de hecho),
    aunque originabotdb todavía la marque en construcción.
    """
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
    gen_first = records_sorted[0].get("generacion") or 0
    gen_last = records_sorted[-1].get("generacion") or 0
    diff_kwh = gen_last - gen_first
    if diff_kwh <= 0:
        return None
    return round((diff_kwh / 1000) / n_days_window, 4)


# ── TODO: cronogramas de construcción Sun Factory (Solenium EPC) ────────────────
# Sun Factory (sunfactory.solenium.co) expone los cronogramas EPC: fecha de
# energización REAL programada + % de avance de obra por proyecto. Cuando esté
# disponible debe devolver, por proyecto: {energization_date, avance_pct, hito}.
# Esos datos tienen PRIORIDAD sobre la estimación de minifarm_projectstagechange.
#
# BLOQUEO ACTUAL (2026-06-02): la cuenta `eduardo` responde "Sin proyectos
# asociados al usuario en sesión" en /api/project/ — no hay proyectos asignados,
# así que los cronogramas per-proyecto no son accesibles. Pendiente: asociar los
# proyectos a la cuenta (admin Solenium) o usar una cuenta de servicio con acceso.
# Auth confirmado OK vía SUNFACTORY_AUTH_URL (JWT). Endpoints: project/, activities/.
def _fetch_sunfactory_cronograma(project_name: str) -> dict | None:
    """No implementado: la cuenta Sun Factory no tiene proyectos asociados (ver nota)."""
    return None


@router.get("")
def proximos_energizar(
    cross_generacion: bool = Query(True, description="Cruzar con la API de generación de Unergy para detectar plantas ya energizadas y usar su promedio real."),
    yield_kwh_kwp_day: float = Query(_DEFAULT_YIELD_KWH_KWP_DAY, ge=1.0, le=8.0, description="Rendimiento específico para la proyección de MWh/mes."),
    _=Depends(get_current_user),
) -> dict:
    """Proyectos en pipeline de construcción con su proyección de generación.

    Forma de cada proyecto (compatible con el frontend):
    `{ id, name, status, energizationDate, contracts, monthlyMwh, ... }`.
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

    token = None
    gen_warning = None
    if cross_generacion:
        try:
            token = _unergy_token()
            if token is None:
                gen_warning = "Credenciales de generación Unergy no configuradas — proyección teórica únicamente."
        except Exception as exc:
            logger.warning("Unergy generation auth failed: %s", exc)
            gen_warning = "No se pudo autenticar con la API de generación de Unergy — proyección teórica únicamente."

    projects = []
    for r in rows:
        (pid, name, stage, installed_power, dc_capacity, contract_type,
         last_stage_date, review_date) = r

        status = _STAGE_TO_STATUS.get(stage, "En construcción")
        energ = _estimate_energization(stage, review_date, last_stage_date)
        monthly = _project_monthly_mwh(installed_power, yield_kwh_kwp_day)
        projection_basis = "potencia_instalada"
        already_generating = False

        if token and name:
            avg = _recent_avg_daily_mwh(token, name)
            if avg and avg > 0:
                already_generating = True
                monthly = round(avg * 30, 2)
                projection_basis = "generacion_real_unergy"
                # La API de generación ya reporta datos → la planta está energizada de hecho.
                if status != "Energizado":
                    status = "Próximo a energizar"

        projects.append({
            "id": pid,
            "name": name,
            "status": status,
            "stage": stage,
            "energizationDate": energ.isoformat() if energ else None,
            "energizationEstimated": review_date is None,
            "contracts": [],
            "monthlyMwh": monthly,
            "installedPowerKwp": installed_power,
            "dcCapacityKwp": dc_capacity,
            "contractType": contract_type,
            "alreadyGenerating": already_generating,
            "projectionBasis": projection_basis,
        })

    result = {"projects": projects, "source": "originabotdb", "count": len(projects),
              "yieldKwhKwpDay": yield_kwh_kwp_day}
    if gen_warning:
        result["warning"] = gen_warning
    return result
