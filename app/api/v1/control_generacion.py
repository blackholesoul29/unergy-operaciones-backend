"""Control de Generación — curvas Quoia + Solenium comparadas por frontera.

Endpoints:
  GET /control-generacion/proyectos  → lista fronteras de Quoia con match Solenium
  GET /control-generacion/datos      → curvas Quoia + Solenium por frontera y fecha
"""
from __future__ import annotations

import logging
import re
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.usuarios import Usuario
from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("control_generacion")
router = APIRouter(prefix="/control-generacion", tags=["Control de Generación"])

# ── Clientes singleton ────────────────────────────────────────────────────────
_solenium: SoleniumClient | None = None
_gaia: GaiaClient | None = None

# Cache de proyectos Solenium (1 hora)
_sol_projects: list[dict] = []
_sol_projects_ts: float = 0.0
_SOL_CACHE_TTL = 3600


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


def _get_sol_projects(sol: SoleniumClient) -> list[dict]:
    global _sol_projects, _sol_projects_ts
    if not _sol_projects or _time.time() - _sol_projects_ts > _SOL_CACHE_TTL:
        try:
            _sol_projects = sol.get_projects() or []
        except Exception as exc:
            logger.warning("solenium get_projects error: %s", exc)
        _sol_projects_ts = _time.time()
    return _sol_projects


def _col_yesterday() -> str:
    col = datetime.now(timezone.utc) - timedelta(hours=5)
    return (col - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Matching Quoia ↔ Solenium (misma lógica que el pipeline ASIC) ─────────────

_STOP_WORDS = {
    "de", "del", "la", "el", "los", "las", "y", "en",
    "minigranja", "mgs", "gd", "sol", "cielo", "frontera",
    "n1", "n2", "n3", "n4", "san", "santa",
}
_SCORE_MIN = 0.5


def _extraer_numero(nombre: str) -> str | None:
    m = re.search(r"\d{4}", nombre)
    return m.group() if m else None


def _tokens(nombre: str) -> set:
    return {
        w for w in re.split(r"[\s\-_&/]+", nombre.lower())
        if len(w) > 2 and w not in _STOP_WORDS
    }


def _score(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _match_solenium(
    quoia_name: str, sol_projects: list[dict]
) -> tuple[int | None, str | None, str | None]:
    """Returns (sol_id, sol_name, method) — method es 'numero', 'token', o None."""
    num = _extraer_numero(quoia_name)

    # Paso 1: match por número de 4 dígitos
    if num:
        for p in sol_projects:
            if _extraer_numero(p.get("name", "")) == num:
                return p["id"], p.get("name", ""), "numero"

    # Paso 2: match por tokens
    if sol_projects:
        best = max(sol_projects, key=lambda p: _score(quoia_name, p.get("name", "")))
        if _score(quoia_name, best.get("name", "")) >= _SCORE_MIN:
            return best["id"], best.get("name", ""), "token"

    return None, None, None


# ── Helpers de datos ──────────────────────────────────────────────────────────

def _quoia_curve(gaia: GaiaClient, frt_code: str, fecha: str) -> dict:
    try:
        rows = gaia.get_border_measurements(frt_code, fecha)
    except Exception as exc:
        logger.warning("gaia border=%s fecha=%s: %s", frt_code, fecha, exc)
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


def _solenium_generation(sol: SoleniumClient, sol_id: int, fecha: str) -> dict:
    # Total horario (para comparar con Quoia)
    total = 0.0
    curva: list[dict] = []
    try:
        gen_data = sol.get_generation(sol_id, start_date=fecha, end_date=fecha)
        if gen_data:
            total = float(gen_data.get("total_generation_kwh", 0) or 0)
            gen_dict = gen_data.get("generation_kwh", {}) or {}
            curva = [
                {"hora": ts[11:16] if len(ts) >= 16 else ts, "kwh": round(float(v or 0), 3)}
                for ts, v in sorted(gen_dict.items())
            ]
    except Exception as exc:
        logger.warning("solenium gen id=%s fecha=%s: %s", sol_id, fecha, exc)

    # Curvas por inversor (potencia kW, 5 min)
    # Estructura real: {"results": {"unit": "kW", "power": {"InversorName": {"HH:MM": kw, ...}, ...}}}
    inversores: list[dict] = []
    try:
        power_data = sol.get_power(sol_id, date_from=fecha, date_to=fecha)
        if power_data:
            power_dict = (power_data.get("results") or {}).get("power") or {}
            for inv_name, ts_dict in power_dict.items():
                if not isinstance(ts_dict, dict):
                    continue
                inv_curva: list[dict] = []
                inv_total = 0.0
                for ts, kw_val in sorted(ts_dict.items()):
                    kw = float(kw_val or 0)
                    hora = ts[11:16] if len(ts) >= 16 else ts
                    inv_total += kw * (5 / 60)
                    inv_curva.append({"tiempo": hora, "kw": round(kw, 3)})
                inversores.append({
                    "id":        inv_name,
                    "nombre":    inv_name,
                    "total_kwh": round(inv_total, 3),
                    "curva":     inv_curva,
                })
    except Exception as exc:
        logger.warning("solenium power id=%s fecha=%s: %s", sol_id, fecha, exc)

    return {"total_kwh": round(total, 3), "curva": curva, "inversores": inversores}


def _discrepancia(q_kwh: float, s_kwh: float) -> float | None:
    ref = max(q_kwh, s_kwh)
    if ref == 0:
        return None
    return round(abs(q_kwh - s_kwh) / ref * 100, 1)


# ── Parsear lista de fronteras Quoia ──────────────────────────────────────────

def _parse_quoia_borders(borders: list[dict], sol_projects: list[dict]) -> list[dict]:
    result = []
    for b in borders:
        frt_gen = b.get("frt_generation")
        if not frt_gen:
            continue
        frt_code = (frt_gen.get("frt_code") or "").strip().lower()
        if not frt_code:
            continue
        nombre = (b.get("name") or frt_code).strip()
        sol_id, sol_nombre, metodo = _match_solenium(nombre, sol_projects)
        result.append({
            "frt_code":     frt_code,
            "nombre":       nombre,
            "estado_quoia": frt_gen.get("status", ""),
            "solenium_id":  sol_id,
            "solenium_nombre": sol_nombre,
            "metodo_match": metodo,
            "tiene_solenium": sol_id is not None,
        })
    result.sort(key=lambda x: x["nombre"])
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/debug-solenium/{sol_id}")
def debug_solenium(
    sol_id: int,
    fecha: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Diagnóstico: devuelve las respuestas crudas de Solenium para un proyecto."""
    if not fecha:
        fecha = _col_yesterday()
    sol = _get_solenium()
    return {
        "inverters":  sol.get_project_inverters(sol_id),
        "generation": sol.get_generation(sol_id, start_date=fecha, end_date=fecha),
        "power":      sol.get_power(sol_id, date_from=fecha, date_to=fecha),
    }

@router.get("/proyectos")
def listar_proyectos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista todas las fronteras de generación de Quoia con su match en Solenium."""
    gaia = _get_gaia()
    sol  = _get_solenium()
    borders      = gaia.get_all_borders()
    sol_projects = _get_sol_projects(sol)
    return {"proyectos": _parse_quoia_borders(borders, sol_projects)}


@router.get("/datos")
def datos_generacion(
    fecha: str | None = Query(None, description="YYYY-MM-DD. Por defecto: ayer en hora Colombia"),
    frt_code: str | None = Query(None, description="Filtrar una frontera específica por código SIC"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Retorna curvas Quoia + Solenium comparadas por frontera.
    Fuente de verdad: Quoia. Match Solenium por nombre (número 4 dígitos o tokens).
    """
    if not fecha:
        fecha = _col_yesterday()
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status_code=422, detail="fecha debe tener formato YYYY-MM-DD")

    gaia = _get_gaia()
    sol  = _get_solenium()

    borders      = gaia.get_all_borders()
    sol_projects = _get_sol_projects(sol)
    parsed       = _parse_quoia_borders(borders, sol_projects)

    if frt_code:
        parsed = [p for p in parsed if p["frt_code"] == frt_code.strip().lower()]

    def _procesar(p: dict) -> dict:
        quoia_data = _quoia_curve(gaia, p["frt_code"], fecha)
        sol_data   = {"total_kwh": 0.0, "curva": []}
        if p["solenium_id"]:
            sol_data = _solenium_generation(sol, p["solenium_id"], fecha)

        q_kwh = quoia_data["total_kwh"]
        s_kwh = sol_data["total_kwh"]
        estado = "con_datos" if (q_kwh > 0 or s_kwh > 0) else "sin_medidas"

        return {
            "frt_code":        p["frt_code"],
            "nombre":          p["nombre"],
            "estado_quoia":    p["estado_quoia"],
            "solenium_id":     p["solenium_id"],
            "solenium_nombre": p["solenium_nombre"],
            "metodo_match":    p["metodo_match"],
            "tiene_solenium":  p["tiene_solenium"],
            "estado":          estado,
            "discrepancia_pct": _discrepancia(q_kwh, s_kwh),
            "quoia":    quoia_data,
            "solenium": sol_data,
        }

    resultados: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_procesar, p): p for p in parsed}
        for fut in as_completed(futures):
            try:
                resultados.append(fut.result())
            except Exception as exc:
                logger.error("error procesando frontera: %s", exc)

    resultados.sort(key=lambda x: x["nombre"])

    return {
        "fecha": fecha,
        "resumen": {
            "total_fronteras":    len(resultados),
            "con_datos":          sum(1 for r in resultados if r["estado"] == "con_datos"),
            "sin_medidas":        sum(1 for r in resultados if r["estado"] == "sin_medidas"),
            "total_quoia_kwh":    round(sum(r["quoia"]["total_kwh"]    for r in resultados), 2),
            "total_solenium_kwh": round(sum(r["solenium"]["total_kwh"] for r in resultados), 2),
        },
        "proyectos": resultados,
    }
