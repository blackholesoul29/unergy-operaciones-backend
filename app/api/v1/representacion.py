"""
Endpoint de Representación CGM.

Lee los contratos directamente de los JSON en data/:
  - DataCGM.json         → metadatos del contrato por proyecto + inversionista
  - IndexacionCGM.json   → indexación CGM por proyecto
  - IndexacionRepre.json → indexación Representación por proyecto + inversionista

Opcionalmente cruza con la BD para obtener el db_id del contrato editable.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.contratos import ContratoServicio

router = APIRouter(prefix="/representacion", tags=["Representacion"])

# ── Rutas de los JSON (relativas al raíz del proyecto) ────────────────────────
_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"


def _read_json(filename: str) -> Any:
    """Lee un archivo JSON manejando BOM y errores de encoding."""
    path = _DATA_DIR / filename
    # utf-8-sig maneja BOM automáticamente
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _load_data_cgm() -> list[dict]:
    """DataCGM.json → sección 'Indexación' (metadatos por proyecto/inversionista)."""
    try:
        raw = _read_json("DataCGM.json")
        if isinstance(raw, dict):
            # La clave puede tener acento o no
            return raw.get("Indexación", raw.get("Indexacion", []))
        return []
    except Exception as e:
        print(f"[representacion] Error cargando DataCGM.json: {e}")
        return []


def _load_idx_cgm() -> list[dict]:
    """
    IndexacionCGM.json — el archivo NO tiene corchetes de array externo.
    Lo envolvemos para parsearlo como JSON válido.
    """
    try:
        path = _DATA_DIR / "IndexacionCGM.json"
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = path.read_text(encoding=enc).strip()
                break
            except UnicodeDecodeError:
                continue
        else:
            return []
        # Si es un array ya válido, parsear directamente
        if text.startswith("["):
            return json.loads(text)
        # Envolver: el archivo es una secuencia de objetos separados por comas
        wrapped = "[" + text + "]"
        return json.loads(wrapped)
    except Exception as e:
        print(f"[representacion] Error cargando IndexacionCGM.json: {e}")
        return []


def _load_idx_rep() -> list[dict]:
    """IndexacionRepre.json → sección 'Indexación'."""
    try:
        raw = _read_json("IndexacionRepre.json")
        if isinstance(raw, dict):
            return raw.get("Indexación", raw.get("Indexacion", []))
        return []
    except Exception as e:
        print(f"[representacion] Error cargando IndexacionRepre.json: {e}")
        return []


# ── IPC rates (DANE) ──────────────────────────────────────────────────────────
_IPC: dict[int, float] = {
    2023: 0.0928,
    2024: 0.052,
    2025: 0.051,
}


def _normalizar_nombre(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _anniversary_date(firma: str, target_year: int) -> str:
    """Devuelve la fecha del aniversario en target_year manteniendo mes/día de firma."""
    if not firma or len(firma) < 10:
        return str(target_year)
    return f"{target_year}-{firma[5:]}"


def _build_cgm_idx(cgm_row: dict | None, firma: str | None) -> list[dict]:
    """Construye la lista de aniversarios CGM con fechas exactas."""
    if not cgm_row:
        return []
    base = cgm_row.get("Tarifa CGM (kWh)") or 0
    if base == 0 and not firma:
        return []

    entries: list[dict] = []
    base_year = int(firma[:4]) if firma else 2025

    # Año base
    entries.append({
        "fecha": firma or str(base_year),
        "anno": base_year,
        "ipc": None,
        "valor": base,
        "es_base": True,
    })

    # 2025 (solo si firma ≤ 2024)
    v2025 = cgm_row.get("IPC aplicado CGM (2025) 5.20%")
    if v2025 is not None and base_year <= 2024:
        entries.append({
            "fecha": _anniversary_date(firma, 2025),
            "anno": 2025,
            "ipc": 5.2,
            "valor": round(v2025, 6),
            "es_base": False,
        })

    # 2026
    v2026 = cgm_row.get("IPC aplicado CGM (2026) 5.10%")
    if v2026 is not None and base_year <= 2025:
        entries.append({
            "fecha": _anniversary_date(firma, 2026),
            "anno": 2026,
            "ipc": 5.1,
            "valor": round(v2026, 6),
            "es_base": False,
        })

    return entries


def _build_rep_idx(rep_row: dict | None, firma: str | None) -> list[dict]:
    """Construye la lista de aniversarios Representación con fechas exactas."""
    if not rep_row:
        return []
    base = rep_row.get("Tarifa Representación (kWh)") or 0
    if base == 0 and not firma:
        return []

    entries: list[dict] = []
    base_year = int(firma[:4]) if firma else 2025

    entries.append({
        "fecha": firma or str(base_year),
        "anno": base_year,
        "ipc": None,
        "valor": base,
        "es_base": True,
    })

    v2025 = rep_row.get("IPC aplicado Repre (2025) 5.20%")
    if v2025 is not None and v2025 > 0 and base_year <= 2024:
        entries.append({
            "fecha": _anniversary_date(firma, 2025),
            "anno": 2025,
            "ipc": 5.2,
            "valor": round(v2025, 6),
            "es_base": False,
        })

    v2026 = rep_row.get("IPC aplicado Repre(2026) 5.10%")
    if v2026 is not None and v2026 > 0 and base_year <= 2025:
        entries.append({
            "fecha": _anniversary_date(firma, 2026),
            "anno": 2026,
            "ipc": 5.1,
            "valor": round(v2026, 6),
            "es_base": False,
        })

    return entries


def _match_proyecto(nombre_json: str, nombre_plataforma: str) -> bool:
    """True si los nombres de proyecto coinciden (fuzzy por número 4 dígitos o palabras clave)."""
    n1 = _normalizar_nombre(nombre_json)
    n2 = _normalizar_nombre(nombre_plataforma)
    if n1 == n2:
        return True
    # Por número de 4 dígitos
    nums = re.findall(r"\d{4}", n2)
    if nums and any(num in n1 for num in nums):
        return True
    # Por código SF del nombre (si se pasa código en lugar de nombre)
    if len(n2) >= 8 and n2 in n1:
        return True
    return False


@router.get("")
def listar_contratos(
    proyecto_nombre: str | None = Query(None, description="Nombre del proyecto en la plataforma"),
    codigo_sun_factory: str | None = Query(None, description="Código TSF / Sun Factory"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Devuelve todos los contratos CGM/Representación para un proyecto,
    con sus indexaciones calculadas y fechas de aniversario exactas.
    """
    data_cgm = _load_data_cgm()
    idx_cgm_list = _load_idx_cgm()
    idx_rep_list = _load_idx_rep()
    today = date.today()

    # ── Filtrar contratos del proyecto ────────────────────────────────────────
    def _matches(c: dict) -> bool:
        pn = c.get("Proyecto", "")
        sf = c.get("Código Sun Factory", "")
        if codigo_sun_factory and sf and sf.strip() == codigo_sun_factory.strip():
            return True
        if proyecto_nombre:
            return _match_proyecto(pn, proyecto_nombre)
        return False

    contratos_proyecto = [c for c in data_cgm if _matches(c)]

    if not contratos_proyecto:
        return []

    # ── Mapa CGM por nombre de proyecto ──────────────────────────────────────
    cgm_by_proyecto: dict[str, dict] = {}
    for row in idx_cgm_list:
        pn = _normalizar_nombre(row.get("Proyecto", ""))
        if pn not in cgm_by_proyecto:
            cgm_by_proyecto[pn] = row

    # ── Mapa Rep por (proyecto, inversionista) ────────────────────────────────
    rep_by_key: dict[tuple, dict] = {}
    for row in idx_rep_list:
        key = (
            _normalizar_nombre(row.get("Proyecto", "")),
            _normalizar_nombre(row.get("Inversionista", "")),
        )
        rep_by_key[key] = row

    # ── Mapa contratos en BD por (proyecto_ref, inversionista) ────────────────
    db_contratos = db.query(ContratoServicio).filter(
        ContratoServicio.servicio_aplica == "representacion",
        ContratoServicio.inversionista_nombre.isnot(None),
    ).all()
    db_by_key: dict[tuple, ContratoServicio] = {}
    for c in db_contratos:
        key = (
            _normalizar_nombre(c.nombre_proyecto_ref or ""),
            _normalizar_nombre(c.inversionista_nombre or ""),
        )
        db_by_key[key] = c

    # ── Construir respuesta ───────────────────────────────────────────────────
    result: list[dict] = []
    for c in contratos_proyecto:
        pn_norm = _normalizar_nombre(c.get("Proyecto", ""))
        inv_norm = _normalizar_nombre(c.get("Inversionista", ""))
        firma = c.get("Firma contrato") or None

        # Buscar CGM indexation por proyecto
        cgm_row = cgm_by_proyecto.get(pn_norm)

        # Buscar Rep indexation por (proyecto, inversionista)
        rep_row = rep_by_key.get((pn_norm, inv_norm))

        # Indexaciones con fechas
        idx_cgm = _build_cgm_idx(cgm_row, firma)
        idx_rep = _build_rep_idx(rep_row, firma)

        # Buscar contrato en BD para edición
        db_c = db_by_key.get((pn_norm, inv_norm))

        # Soporte: solo devolver si es URL
        soporte = c.get("Soporte") or ""
        soporte_url = soporte if soporte.startswith("http") else None

        result.append({
            "proyecto": c.get("Proyecto", "").strip(),
            "codigo_sun_factory": c.get("Código Sun Factory", "").strip() or None,
            "portafolio": c.get("Portafolio", "").strip() or None,
            "inversionista": c.get("Inversionista", "").strip(),
            "estado": (c.get("Estado") or "").strip() or None,
            "tarifa_admin": c.get("Tarifa Admin (%)"),
            "tarifa_cgm": c.get("Tarifa CGM (kWh)"),
            "tarifa_rep": c.get("Tarifa Representación (kWh)"),
            "fecha_firma": firma,
            "soporte_url": soporte_url,
            "indexacion_cgm": idx_cgm,
            "indexacion_rep": idx_rep,
            "db_id": db_c.id if db_c else None,
        })

    return result
