"""
Cross-database project correlation: operaciones ↔ originabotdb ↔ requestsdb.

Connects the three databases that track the same solar projects:
- operaciones (this DB): proyectos table — internal operations
- originabotdb: origina platform — supply requests, commercial data
- requestsdb: grid infrastructure — transformers, circuits, substations

Correlation strategy:
1. Name matching: fuzzy match proyecto.nombre ↔ origina mp.name ↔ Quoia node name
2. Frontera code: proyecto.codigo_tsf ↔ origina frontera code
3. Grid mapping: grid_map.py enriches with subestacion/circuito/OR from requestsdb

All external DB queries are read-only.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from contextlib import contextmanager

import psycopg
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger("correlation")


def _normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    text_clean = "".join(c for c in nfkd if not unicodedata.combining(c))
    text_clean = text_clean.lower().strip()
    text_clean = re.sub(r"^minigranja\s*(solar\s*)?", "", text_clean)
    text_clean = re.sub(r"^mgs\s*", "", text_clean)
    text_clean = re.sub(r"^\d{4}\s*-\s*", "", text_clean)
    for suffix in ("principal", "respaldo", "repaldo"):
        text_clean = re.sub(rf"\s*{suffix}\s*$", "", text_clean)
    text_clean = re.sub(r"\s+", " ", text_clean).strip()
    return text_clean


@contextmanager
def _origina_conn():
    if not settings.ORIGINA_DATABASE_URL:
        yield None
        return
    url = settings.ORIGINA_DATABASE_URL
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    conn = psycopg.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _requestsdb_conn():
    if not settings.REQUESTSDB_DATABASE_URL:
        yield None
        return
    url = settings.REQUESTSDB_DATABASE_URL
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    conn = psycopg.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def fetch_origina_projects() -> list[dict]:
    """Fetch project list from originabotdb (read-only).

    Table: minifarm_project (aliased mp in queries).
    Key columns: id, name (code like COLCEST45P7_VALLEDUPAR_SUR),
    stage (operation/construction/deploy), lat, lng,
    project_installed_power, project_dc_capacity, project_panels_count.
    """
    with _origina_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.execute("""
                SELECT id, name, stage,
                       lat, lng,
                       project_installed_power,
                       project_dc_capacity,
                       project_panels_count
                FROM minifarm_project
                ORDER BY name
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("origina query failed: %s", e)
            return []


def fetch_requestsdb_supplies() -> list[dict]:
    """Fetch supply requests from requestsdb (read-only)."""
    with _requestsdb_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.execute("""
                SELECT
                    sr.id AS supply_id,
                    sr.project_name,
                    t.name AS transformer_name,
                    c.name AS circuit_name,
                    s.name AS substation_name
                FROM supplies_supplyrequest sr
                LEFT JOIN supplies_transformer t ON sr.transformer_id = t.id
                LEFT JOIN supplies_circuit c ON t.circuit_id = c.id
                LEFT JOIN supplies_substation s ON c.substation_id = s.id
                ORDER BY sr.project_name
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("requestsdb query failed: %s", e)
            return []


def correlate_projects(db: Session) -> dict:
    """Run cross-database correlation and update proyectos with matches."""
    rows = db.execute(text(
        "SELECT id, nombre, codigo_tsf, alias_monitoreo, origina_code, quoia_node_name "
        "FROM proyectos WHERE estado = 'en_operacion' ORDER BY nombre"
    )).mappings().all()

    ops_projects = [dict(r) for r in rows]
    origina_projects = fetch_origina_projects()
    requestsdb_supplies = fetch_requestsdb_supplies()

    origina_by_norm: dict[str, dict] = {}
    origina_by_code: dict[str, dict] = {}
    for op in origina_projects:
        code = op.get("name") or ""
        origina_by_code[code.upper()] = op
        # Extract human-readable name from origina code: COLCEST45P7_VALLEDUPAR_SUR → valledupar sur
        parts = code.split("_", 1)
        readable = parts[1].replace("_", " ").lower() if len(parts) > 1 else code.lower()
        if readable:
            origina_by_norm[readable] = op

    supply_by_norm: dict[str, dict] = {}
    for sr in requestsdb_supplies:
        name = sr.get("project_name") or ""
        norm = _normalize(name)
        if norm:
            supply_by_norm[norm] = sr

    matched = 0
    results: list[dict] = []

    for proj in ops_projects:
        nombre = proj["nombre"] or ""
        norm = _normalize(nombre)
        alias_norm = _normalize(proj.get("alias_monitoreo") or "")

        match_info: dict = {
            "proyecto_id": proj["id"],
            "nombre": nombre,
            "origina_match": None,
            "requestsdb_match": None,
        }

        # Try origina match
        origina_hit = origina_by_norm.get(norm) or origina_by_norm.get(alias_norm)
        if not origina_hit:
            for on, op in origina_by_norm.items():
                if norm and (norm in on or on in norm):
                    origina_hit = op
                    break

        if origina_hit:
            code = origina_hit.get("name")
            match_info["origina_match"] = code
            if code and not proj.get("origina_code"):
                db.execute(text(
                    "UPDATE proyectos SET origina_code = :code WHERE id = :pid"
                ), {"code": code, "pid": proj["id"]})
                matched += 1

        # Try requestsdb match
        supply_hit = supply_by_norm.get(norm) or supply_by_norm.get(alias_norm)
        if not supply_hit:
            for sn, sr in supply_by_norm.items():
                if norm and (norm in sn or sn in norm):
                    supply_hit = sr
                    break

        if supply_hit:
            match_info["requestsdb_match"] = {
                "supply_id": supply_hit.get("supply_id"),
                "transformer": supply_hit.get("transformer_name"),
                "circuit": supply_hit.get("circuit_name"),
                "substation": supply_hit.get("substation_name"),
            }
            sid = supply_hit.get("supply_id")
            if sid and not proj.get("requestsdb_supply_id"):
                db.execute(text(
                    "UPDATE proyectos SET requestsdb_supply_id = :sid WHERE id = :pid"
                ), {"sid": sid, "pid": proj["id"]})
                matched += 1

        results.append(match_info)

    db.commit()

    return {
        "total_operations_projects": len(ops_projects),
        "origina_projects_found": len(origina_projects),
        "requestsdb_supplies_found": len(requestsdb_supplies),
        "correlations_updated": matched,
        "details": results,
    }


def get_project_cross_view(db: Session, proyecto_id: int) -> dict:
    """Get unified cross-database view for a single project."""
    from app.services.mgs.grid_map import get_grid_info

    row = db.execute(text("""
        SELECT id, nombre, codigo_tsf, alias_monitoreo,
               origina_code, requestsdb_supply_id, quoia_node_name
        FROM proyectos WHERE id = :pid
    """), {"pid": proyecto_id}).mappings().first()

    if not row:
        return {"error": "Proyecto no encontrado"}

    proj = dict(row)
    grid = get_grid_info(proj["nombre"] or "")

    result = {
        "proyecto": proj,
        "grid_info": grid,
        "origina": None,
        "requestsdb": None,
    }

    if proj.get("origina_code"):
        origina_projects = fetch_origina_projects()
        for op in origina_projects:
            if op.get("name") == proj["origina_code"]:
                result["origina"] = op
                break

    if proj.get("requestsdb_supply_id"):
        supplies = fetch_requestsdb_supplies()
        for sr in supplies:
            if sr.get("supply_id") == proj["requestsdb_supply_id"]:
                result["requestsdb"] = sr
                break

    return result
