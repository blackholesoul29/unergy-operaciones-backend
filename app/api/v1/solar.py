"""
Endpoints de Monitoreo Solar — datos XM SinergoX.
Lee dos archivos Excel en ./datos/ y expone endpoints REST.

Archivos requeridos (generados por solar_sin.py):
  ./datos/listado_recursos.xlsx       → metadatos de proyectos RAD Solar
  ./datos/generacion_distribuida.xlsx → generación horaria por proyecto y fecha

Caché en memoria con TTL de 5 minutos.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db

router = APIRouter(prefix="/solar", tags=["Solar"])

# ─── Rutas a los Excel ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parents[3]
DATOS_DIR = BASE_DIR / "datos"
RECURSOS_FILE = DATOS_DIR / "listado_recursos.xlsx"
GENERACION_FILE = DATOS_DIR / "generacion_distribuida.xlsx"

# ─── Caché en memoria ─────────────────────────────────────────────────────────
_cache: dict = {}
_cache_ts: float = 0.0
CACHE_TTL = 300  # segundos


# ─── Utilidades de parsing ────────────────────────────────────────────────────

def _norm(s: object) -> str:
    """Normaliza un string: minúsculas, sin tildes, sin espacios → clave de comparación."""
    return (
        str(s or "")
        .lower()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ü", "u")
        .replace(" ", "_").replace("[", "").replace("]", "").replace(".", "")
        .strip()
    )


def _find_col(header_map: dict[str, str], *candidates: str) -> str | None:
    """Devuelve el nombre original del header que coincida con algún candidato."""
    for c in candidates:
        k = _norm(c)
        if k in header_map:
            return header_map[k]
    return None


def _parse_date(raw: object) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _read_sheet(path: Path) -> tuple[list[str], list[tuple]]:
    """Lee la primera hoja del Excel. Devuelve (headers, data_rows)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not all_rows:
        return [], []
    headers = [str(c or "").strip() for c in all_rows[0]]
    return headers, all_rows[1:]


# ─── Carga y construcción de datos ────────────────────────────────────────────

def _build_data() -> dict:
    """Construye proyectos + registros de generación desde los Excel.
    Devuelve {'proyectos': [...], 'generacion': [...]}."""

    proyectos: list[dict] = []
    generacion: list[dict] = []

    # ── 1. Cargar metadatos de recursos ──────────────────────────────────────
    if not RECURSOS_FILE.exists():
        return {"proyectos": [], "generacion": []}

    headers_r, rows_r = _read_sheet(RECURSOS_FILE)
    hmap_r = {_norm(h): h for h in headers_r}

    col_sic   = _find_col(hmap_r, "Código SIC", "Codigo SIC", "CODIGO SIC", "SIC", "Código SIC Recurso")
    col_nom   = _find_col(hmap_r, "Nombre Recurso", "Nombre", "NOMBRE RECURSO", "Nombre del Recurso")
    col_mun   = _find_col(hmap_r, "Municipio", "MUNICIPIO", "Municipio Recurso")
    col_dep   = _find_col(hmap_r, "Departamento", "DEPARTAMENTO", "Departamento Recurso")
    col_age   = _find_col(hmap_r, "Agente Representante", "Agente", "AGENTE", "Agente Propietario")
    col_est   = _find_col(hmap_r, "Estado Recurso", "Estado", "ESTADO", "Estado del Recurso")
    col_cap   = _find_col(hmap_r, "Capacidad Efectiva Neta [MW]", "Capacidad Efectiva Neta",
                          "Capacidad MW", "Capacidad Efectiva Neta MW", "Capacidad_Efectiva_Neta")
    col_tipo  = _find_col(hmap_r, "Tipo Generación", "Tipo Generacion", "TIPO GENERACION",
                          "Tipo de Generación", "Tipo")

    def _get(row: tuple, col: str | None) -> object:
        if col is None:
            return None
        try:
            return row[headers_r.index(col)]
        except (ValueError, IndexError):
            return None

    seen_sic: set[str] = set()
    for row in rows_r:
        tipo = str(_get(row, col_tipo) or "").strip().upper()
        if tipo != "SOLAR":
            continue
        sic = str(_get(row, col_sic) or "").strip()
        if not sic or sic in seen_sic:
            continue
        seen_sic.add(sic)
        try:
            cap = float(_get(row, col_cap) or 0)
        except (TypeError, ValueError):
            cap = 0.0
        proyectos.append({
            "sic":          sic,
            "nombre":       str(_get(row, col_nom) or sic).strip(),
            "municipio":    str(_get(row, col_mun) or "").strip(),
            "departamento": str(_get(row, col_dep) or "").strip(),
            "agente":       str(_get(row, col_age) or "").strip(),
            "estado":       str(_get(row, col_est) or "").strip().upper(),
            "capacidad_mw": round(cap, 4),
        })

    if not proyectos:
        return {"proyectos": [], "generacion": []}

    # ── 2. Cargar generación horaria ──────────────────────────────────────────
    if not GENERACION_FILE.exists():
        return {"proyectos": proyectos, "generacion": []}

    sic_meta = {p["sic"]: p for p in proyectos}

    headers_g, rows_g = _read_sheet(GENERACION_FILE)
    hmap_g = {_norm(h): h for h in headers_g}

    col_sic_g = _find_col(hmap_g, "Código SIC Recurso", "Codigo SIC Recurso", "Código SIC",
                          "SIC Recurso", "SIC")
    col_fecha = _find_col(hmap_g, "Fecha", "Fecha Operación", "Fecha_Operacion",
                          "Fecha Operacion", "FechaOperacion", "Date")

    # Columnas de horas 0-23
    def _find_hour_idx(h: int) -> int | None:
        for cand in (str(h), f"hora_{h}", f"hora {h}", f"H{h:02d}", f"h{h}"):
            k = _norm(cand)
            if k in hmap_g:
                try:
                    return headers_g.index(hmap_g[k])
                except ValueError:
                    pass
        # también intentar como índice entero en headers
        for i, hdr in enumerate(headers_g):
            try:
                if int(str(hdr).strip()) == h:
                    return i
            except (ValueError, TypeError):
                pass
        return None

    hour_idxs: list[int | None] = [_find_hour_idx(h) for h in range(24)]

    try:
        sic_g_idx = headers_g.index(col_sic_g) if col_sic_g else None
        fecha_idx = headers_g.index(col_fecha) if col_fecha else None
    except ValueError:
        sic_g_idx = fecha_idx = None

    for row in rows_g:
        sic = str(row[sic_g_idx] if sic_g_idx is not None and sic_g_idx < len(row) else "").strip()
        if sic not in sic_meta:
            continue
        fecha = _parse_date(row[fecha_idx] if fecha_idx is not None and fecha_idx < len(row) else None)
        if fecha is None:
            continue

        # Suma 24 horas. XM reporta en MWh → multiplicamos × 1000 para obtener kWh.
        kwh = 0.0
        for idx in hour_idxs:
            if idx is not None and idx < len(row):
                try:
                    kwh += float(row[idx] or 0) * 1000
                except (TypeError, ValueError):
                    pass

        meta = sic_meta[sic]
        generacion.append({
            "sic":          sic,
            "nombre":       meta["nombre"],
            "municipio":    meta["municipio"],
            "departamento": meta["departamento"],
            "agente":       meta["agente"],
            "estado":       meta["estado"],
            "capacidad_mw": meta["capacidad_mw"],
            "fecha":        fecha.isoformat(),
            "kwh":          round(kwh, 2),
        })

    return {"proyectos": proyectos, "generacion": generacion}


def _load_data() -> dict:
    """Devuelve datos desde caché o los reconstruye si expiró el TTL."""
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    _cache = _build_data()
    _cache_ts = now
    return _cache


def _filter_gen(
    rows: list[dict],
    fecha_ini: str | None,
    fecha_fin: str | None,
    municipios: str | None,
    departamentos: str | None,
    estados: str | None,
) -> list[dict]:
    """Aplica filtros de fecha, municipio, departamento y estado a la lista de generación."""
    if fecha_ini:
        rows = [r for r in rows if r["fecha"] >= fecha_ini]
    if fecha_fin:
        rows = [r for r in rows if r["fecha"] <= fecha_fin]
    if municipios:
        m_set = {m.strip().upper() for m in municipios.split(",") if m.strip()}
        rows = [r for r in rows if r["municipio"].upper() in m_set]
    if departamentos:
        d_set = {d.strip().upper() for d in departamentos.split(",") if d.strip()}
        rows = [r for r in rows if r["departamento"].upper() in d_set]
    if estados:
        e_set = {e.strip().upper() for e in estados.split(",") if e.strip()}
        rows = [r for r in rows if r["estado"].upper() in e_set]
    return rows


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/proyectos", summary="Lista proyectos RAD Solar")
def get_proyectos(_: object = Depends(get_current_user)) -> list[dict]:
    """Devuelve todos los proyectos solares del archivo listado_recursos.xlsx."""
    return _load_data()["proyectos"]


@router.get("/filtros", summary="Valores únicos para los selectores")
def get_filtros(_: object = Depends(get_current_user)) -> dict:
    """Devuelve municipios, departamentos y estados únicos para poblar los filtros."""
    data = _load_data()
    projs = data["proyectos"]
    return {
        "municipios":    sorted({p["municipio"]    for p in projs if p["municipio"]}),
        "departamentos": sorted({p["departamento"] for p in projs if p["departamento"]}),
        "estados":       sorted({p["estado"]       for p in projs if p["estado"]}),
    }


@router.get("/generacion", summary="Generación diaria filtrada")
def get_generacion(
    fechaIni:     Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    fechaFin:     Optional[str] = Query(None, description="Fecha fin YYYY-MM-DD"),
    municipio:    Optional[str] = Query(None, description="Municipios separados por coma"),
    departamento: Optional[str] = Query(None, description="Departamentos separados por coma"),
    estado:       Optional[str] = Query(None, description="Estados separados por coma (OPERACIÓN, PRUEBAS…)"),
    _: object = Depends(get_current_user),
) -> list[dict]:
    """Generación diaria por proyecto, con filtros opcionales."""
    rows = _load_data()["generacion"]
    return _filter_gen(rows, fechaIni, fechaFin, municipio, departamento, estado)


@router.get("/ranking", summary="Top N proyectos por generación total")
def get_ranking(
    fechaIni:     Optional[str] = Query(None),
    fechaFin:     Optional[str] = Query(None),
    municipio:    Optional[str] = Query(None),
    departamento: Optional[str] = Query(None),
    estado:       Optional[str] = Query(None),
    top:          int = Query(15, ge=1, le=100, description="Cantidad de proyectos a retornar"),
    _: object = Depends(get_current_user),
) -> list[dict]:
    """Retorna los top N proyectos con mayor generación en el período filtrado."""
    rows = _load_data()["generacion"]
    filtered = _filter_gen(rows, fechaIni, fechaFin, municipio, departamento, estado)

    agg: dict[str, dict] = {}
    for r in filtered:
        sic = r["sic"]
        if sic not in agg:
            agg[sic] = {
                "sic": sic, "nombre": r["nombre"],
                "municipio": r["municipio"], "departamento": r["departamento"],
                "kwh_total": 0.0, "dias": set(),
            }
        agg[sic]["kwh_total"] += r["kwh"]
        agg[sic]["dias"].add(r["fecha"])

    result = []
    for v in sorted(agg.values(), key=lambda x: x["kwh_total"], reverse=True)[:top]:
        dias = len(v["dias"])
        result.append({
            "sic":          v["sic"],
            "nombre":       v["nombre"],
            "municipio":    v["municipio"],
            "departamento": v["departamento"],
            "kwh_total":    round(v["kwh_total"], 2),
            "dias":         dias,
            "kwh_dia_prom": round(v["kwh_total"] / dias, 2) if dias else 0.0,
        })
    return result


@router.get("/comparacion", summary="Compara proyectos XM vs proyectos internos BD")
def get_comparacion(
    fechaIni:      Optional[str] = Query(None),
    fechaFin:      Optional[str] = Query(None),
    sicNacionales: Optional[str] = Query(None, description="SIC codes separados por coma"),
    idsInternos:   Optional[str] = Query(None, description="IDs de proyectos BD separados por coma"),
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
) -> dict:
    """
    Compara la generación de proyectos nacionales (archivo XM) contra proyectos
    operativos internos registrados en la base de datos.
    """
    result: dict = {"nacionales": [], "internos": []}

    # ── Proyectos nacionales (Excel XM) ──────────────────────────────────────
    if sicNacionales:
        sics = {s.strip() for s in sicNacionales.split(",") if s.strip()}
        rows = _load_data()["generacion"]
        if fechaIni:
            rows = [r for r in rows if r["fecha"] >= fechaIni]
        if fechaFin:
            rows = [r for r in rows if r["fecha"] <= fechaFin]

        by_sic: dict[str, dict] = {}
        for r in rows:
            if r["sic"] not in sics:
                continue
            if r["sic"] not in by_sic:
                by_sic[r["sic"]] = {"nombre": r["nombre"], "daily": defaultdict(float)}
            by_sic[r["sic"]]["daily"][r["fecha"]] += r["kwh"]

        for sic in sics:
            if sic not in by_sic:
                continue
            daily = [
                {"fecha": f, "kwh": round(v, 2)}
                for f, v in sorted(by_sic[sic]["daily"].items())
            ]
            result["nacionales"].append({"sic": sic, "nombre": by_sic[sic]["nombre"], "daily": daily})

    # ── Proyectos internos (base de datos) ────────────────────────────────────
    if idsInternos:
        from app.models.generacion import GeneracionDiaria  # noqa: PLC0415
        from app.models.proyectos import Proyecto           # noqa: PLC0415

        for raw_id in idsInternos.split(","):
            raw_id = raw_id.strip()
            if not raw_id.isdigit():
                continue
            pid = int(raw_id)
            proyecto = db.query(Proyecto).filter(Proyecto.id == pid).first()
            if not proyecto:
                continue
            q = db.query(GeneracionDiaria).filter(GeneracionDiaria.proyecto_id == pid)
            if fechaIni:
                q = q.filter(GeneracionDiaria.fecha >= fechaIni)
            if fechaFin:
                q = q.filter(GeneracionDiaria.fecha <= fechaFin)
            daily = [
                {"fecha": str(r.fecha), "kwh": float(r.kwh_real or 0)}
                for r in q.order_by(GeneracionDiaria.fecha).all()
            ]
            result["internos"].append({
                "id":     pid,
                "nombre": proyecto.nombre_comercial,
                "daily":  daily,
            })

    return result


@router.post("/reload-cache", summary="Fuerza recarga del caché de Excel")
def reload_cache(_: object = Depends(get_current_user)) -> dict:
    """Invalida el caché en memoria y reconstruye los datos desde los archivos Excel."""
    global _cache, _cache_ts
    _cache = {}
    _cache_ts = 0.0
    data = _load_data()
    return {
        "ok":                   True,
        "proyectos":            len(data["proyectos"]),
        "registros_generacion": len(data["generacion"]),
        "archivos": {
            "listado_recursos":        RECURSOS_FILE.exists(),
            "generacion_distribuida":  GENERACION_FILE.exists(),
        },
    }
