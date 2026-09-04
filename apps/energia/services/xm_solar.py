"""Monitoreo Solar nacional — los dos Excel de XM SinergoX.

Lee `datos/listado_recursos.xlsx` (metadatos de los recursos RAD Solar) y
`datos/generacion_distribuida.xlsx` (generación horaria), los cruza por código
SIC y deja en memoria la lista de proyectos y la de generación diaria. Los
genera `solar_sin.py`; este módulo solo los consume.

Portado desde `app/api/v1/solar.py`: es parseo puro, sin base de datos y sin
framework, así que el traslado no cambió la lógica.

**Los encabezados se buscan por candidatos, no por posición.** XM cambia los
nombres de columna entre descargas ("Código SIC", "CODIGO SIC", "SIC"…), así
que `_find_col` prueba varias formas normalizadas antes de rendirse. Lo mismo
con las 24 columnas horarias.

`ponytail: caché en un dict de módulo con TTL de 5 min`. Los Excel se
reconstruyen enteros en cada expiración porque son pequeños y el parseo es
rápido; con `WORKERS=1` un solo proceso lo comparte. Si crecen, el paso
siguiente es materializarlos en una tabla, no cachear más fino.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

import openpyxl

BASE_DIR = Path(__file__).resolve().parents[3]
DATOS_DIR = BASE_DIR / "datos"
RECURSOS_FILE = DATOS_DIR / "listado_recursos.xlsx"
GENERACION_FILE = DATOS_DIR / "generacion_distribuida.xlsx"

CACHE_TTL = 300
_cache: dict = {}
_cache_ts: float = 0.0


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

def construir_datos() -> dict:
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


def datos() -> dict:
    """Devuelve datos desde caché o los reconstruye si expiró el TTL."""
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    _cache = construir_datos()
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


def invalidar_cache() -> None:
    """Fuerza que la próxima lectura reconstruya desde los Excel."""
    global _cache, _cache_ts
    _cache, _cache_ts = {}, 0.0


def filtrar_generacion(
    filas: list[dict], fecha_ini=None, fecha_fin=None,
    municipios=None, departamentos=None, estados=None,
) -> list[dict]:
    """Filtros de fecha y de listas separadas por coma.

    Las fechas se comparan como CADENA ISO, no como `date`: el formato
    `YYYY-MM-DD` ordena igual en texto y ahorra convertir 24 000 filas.
    """
    if fecha_ini:
        filas = [f for f in filas if f["fecha"] >= fecha_ini]
    if fecha_fin:
        filas = [f for f in filas if f["fecha"] <= fecha_fin]
    for campo, crudo in (
        ("municipio", municipios),
        ("departamento", departamentos),
        ("estado", estados),
    ):
        if not crudo:
            continue
        permitidos = {v.strip().upper() for v in crudo.split(",") if v.strip()}
        filas = [f for f in filas if f[campo].upper() in permitidos]
    return filas
