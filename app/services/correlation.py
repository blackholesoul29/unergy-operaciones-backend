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

    Table: minifarm_project — central table with 3,084 projects.
    Only fetches non-dead projects (operation, construction, deploy, signed, portfolio).
    """
    with _origina_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.execute("""
                SELECT mp.id, mp.name, mp.stage,
                       mp.lat, mp.lng,
                       mp.project_installed_power AS kw_ac,
                       mp.project_dc_capacity AS kw_dc,
                       mp.project_panels_count AS panels,
                       mp.contract_type,
                       mp.circuit,
                       mp.grid_operator_id AS grid_operator,
                       tc.name AS city_name,
                       mp.area_m2
                FROM minifarm_project mp
                LEFT JOIN territorial_city tc ON mp.city_id = tc.id
                WHERE mp.stage NOT IN ('dead', 'prospect')
                ORDER BY mp.name
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("origina query failed: %s", e)
            return []


def fetch_origina_viabilities(project_ids: list[int]) -> dict[int, list[dict]]:
    """Fetch viability assessments for given origina project IDs."""
    if not project_ids:
        return {}
    with _origina_conn() as conn:
        if conn is None:
            return {}
        try:
            placeholders = ",".join(str(int(pid)) for pid in project_ids)
            cur = conn.execute(f"""
                SELECT project_id, type, status, comment
                FROM minifarm_viability
                WHERE project_id IN ({placeholders})
                ORDER BY project_id, type
            """)
            result: dict[int, list[dict]] = {}
            for row in cur.fetchall():
                pid = row[0]
                if pid not in result:
                    result[pid] = []
                result[pid].append({"type": row[1], "status": row[2], "comment": row[3]})
            return result
        except Exception as e:
            logger.error("origina viability query failed: %s", e)
            return {}


def fetch_requestsdb_supplies() -> list[dict]:
    """Fetch active supply requests from requestsdb with grid topology."""
    with _requestsdb_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.execute("""
                SELECT
                    sr.id AS supply_id,
                    sr.project AS origina_project_id,
                    sr.project_name,
                    sr.external_code,
                    sr.kwp,
                    sr.kva,
                    go.code AS grid_operator_code,
                    go.name AS grid_operator_name,
                    c.name AS circuit_name,
                    sub.name AS substation_name,
                    sr.type_supply,
                    sr.documentation_status,
                    sr.network_project_status,
                    tc.name AS city_name,
                    tr.name AS department_name
                FROM supplies_supplyrequest sr
                LEFT JOIN management_gridoperator go ON sr.grid_operator_id = go.code
                LEFT JOIN management_transformer t ON sr.transformer_id = t.id
                LEFT JOIN management_circuit c ON t.circuit_id = c.id
                LEFT JOIN management_substation_circuits msc ON c.id = msc.circuit_id
                LEFT JOIN management_substation sub ON msc.substation_id = sub.id
                LEFT JOIN territorial_city tc ON sr.city_id = tc.id
                LEFT JOIN territorial_region tr ON tc.region_id = tr.id
                WHERE sr.type_supply = 'active'
                ORDER BY sr.project_name
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("requestsdb query failed: %s", e)
            return []


def fetch_requestsdb_status_history(supply_ids: list[int]) -> dict[int, list[dict]]:
    """Fetch latest status for given supply request IDs."""
    if not supply_ids:
        return {}
    with _requestsdb_conn() as conn:
        if conn is None:
            return {}
        try:
            placeholders = ",".join(str(int(sid)) for sid in supply_ids)
            cur = conn.execute(f"""
                SELECT DISTINCT ON (ssr.supply_request_id)
                    ssr.supply_request_id,
                    ossr.name AS status_name,
                    ssr.created AS status_date,
                    ssr.updated_by
                FROM supplies_statussupplyrequest ssr
                JOIN supplies_optionstatussupplyrequest ossr ON ssr.status_id = ossr.id
                WHERE ssr.supply_request_id IN ({placeholders})
                ORDER BY ssr.supply_request_id, ssr.created DESC
            """)
            result: dict[int, list[dict]] = {}
            for row in cur.fetchall():
                sid = row[0]
                result[sid] = [{"status": row[1], "date": str(row[2])[:10], "by": row[3]}]
            return result
        except Exception as e:
            logger.error("requestsdb status query failed: %s", e)
            return {}


def fetch_origina_investments() -> list[dict]:
    """Fetch investment funds from originabotdb with their portfolios and project counts.

    Chain: investment_investment -> investment_portfolio_investments ->
           investment_portfolio -> investment_portfolio_minifarm ->
           investment_minifarm -> minifarm_project
    """
    with _origina_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.execute("""
                SELECT
                    ii.id,
                    ii.code,
                    ii.name,
                    ii.email,
                    ii.phone,
                    ii.status,
                    ii.rut,
                    ii.business_registry,
                    COUNT(DISTINCT ip.id) AS portfolio_count,
                    COUNT(DISTINCT im.id) AS minifarm_count,
                    COALESCE(SUM(mp.project_installed_power), 0) AS total_kw
                FROM investment_investment ii
                LEFT JOIN investment_portfolio_investments ipi ON ipi.investment_id = ii.id
                LEFT JOIN investment_portfolio ip ON ip.id = ipi.portfolio_id
                LEFT JOIN investment_portfolio_minifarm ipm ON ipm.portfolio_id = ip.id
                LEFT JOIN investment_minifarm im ON im.id = ipm.minifarm_id
                LEFT JOIN minifarm_project mp ON mp.id = im.project_id
                WHERE ii.status IN ('investment', 'portfolio', 'dd', 'open')
                GROUP BY ii.id, ii.code, ii.name, ii.email, ii.phone,
                         ii.status, ii.rut, ii.business_registry
                ORDER BY ii.name
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("origina investments query failed: %s", e)
            return []


def fetch_origina_investment_detail(investment_id: int) -> dict | None:
    """Fetch a single investment fund with its portfolios and minifarms."""
    with _origina_conn() as conn:
        if conn is None:
            return None
        try:
            # Fund info
            cur = conn.execute("""
                SELECT id, code, name, email, phone, status, rut, business_registry
                FROM investment_investment
                WHERE id = %s
            """, (investment_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            fund = dict(zip(cols, row))

            # Portfolios with minifarms
            cur2 = conn.execute("""
                SELECT
                    ip.id AS portfolio_id,
                    ip.name AS portfolio_name,
                    ip.expected,
                    ip.financing,
                    im.id AS minifarm_id,
                    im.name AS minifarm_name,
                    mp.id AS project_id,
                    mp.name AS project_name,
                    mp.stage,
                    mp.project_installed_power AS kw
                FROM investment_portfolio_investments ipi
                JOIN investment_portfolio ip ON ip.id = ipi.portfolio_id
                LEFT JOIN investment_portfolio_minifarm ipm ON ipm.portfolio_id = ip.id
                LEFT JOIN investment_minifarm im ON im.id = ipm.minifarm_id
                LEFT JOIN minifarm_project mp ON mp.id = im.project_id
                WHERE ipi.investment_id = %s
                ORDER BY ip.name, im.name
            """, (investment_id,))
            cols2 = [d.name for d in cur2.description]
            port_rows = [dict(zip(cols2, r)) for r in cur2.fetchall()]

            # Group by portfolio
            portfolios: dict[int, dict] = {}
            for pr in port_rows:
                pid = pr["portfolio_id"]
                if pid not in portfolios:
                    portfolios[pid] = {
                        "id": pid,
                        "name": pr["portfolio_name"],
                        "expected": pr["expected"],
                        "financing": pr["financing"],
                        "minifarms": [],
                    }
                if pr.get("minifarm_id"):
                    portfolios[pid]["minifarms"].append({
                        "id": pr["minifarm_id"],
                        "name": pr["minifarm_name"],
                        "project_id": pr["project_id"],
                        "project_name": pr["project_name"],
                        "stage": pr["stage"],
                        "kw": float(pr["kw"]) if pr["kw"] else None,
                    })

            fund["portfolios"] = list(portfolios.values())
            return fund
        except Exception as e:
            logger.error("origina investment detail query failed: %s", e)
            return None


def correlate_investments(db: Session) -> dict:
    """Match investment funds from origina with clients in operations DB.

    Matching strategy (in priority order):
    1. NIT/RUT: cliente.nit_cedula == investment.rut or investment.business_registry
    2. Name: fuzzy substring match between cliente.razon_social_nombre and investment.name
    """
    investments = fetch_origina_investments()
    if not investments:
        return {"matched": 0, "investments": 0, "details": []}

    rows = db.execute(text(
        "SELECT id, razon_social_nombre, nit_cedula, origina_investment_id "
        "FROM clientes WHERE deleted_at IS NULL ORDER BY razon_social_nombre"
    )).mappings().all()
    clients = [dict(r) for r in rows]

    # Build lookup indexes for clients
    clients_by_nit: dict[str, dict] = {}
    clients_by_norm_name: dict[str, dict] = {}
    for c in clients:
        nit = (c.get("nit_cedula") or "").strip()
        if nit:
            clients_by_nit[nit] = c
        name = (c.get("razon_social_nombre") or "").strip()
        norm = _normalize(name)
        if norm:
            clients_by_norm_name[norm] = c

    matched = 0
    details: list[dict] = []

    for inv in investments:
        inv_id = inv["id"]
        inv_rut = (inv.get("rut") or "").strip()
        inv_biz_reg = (inv.get("business_registry") or "").strip()
        inv_name = (inv.get("name") or "").strip()
        inv_norm = _normalize(inv_name)

        match_client: dict | None = None
        match_method: str | None = None

        # 1. Match by NIT/RUT
        if inv_rut and inv_rut in clients_by_nit:
            match_client = clients_by_nit[inv_rut]
            match_method = "nit_rut"
        elif inv_biz_reg and inv_biz_reg in clients_by_nit:
            match_client = clients_by_nit[inv_biz_reg]
            match_method = "business_registry"

        # 2. Fuzzy name match
        if not match_client and inv_norm:
            for cn, cc in clients_by_norm_name.items():
                if inv_norm and (inv_norm in cn or cn in inv_norm):
                    match_client = cc
                    match_method = "name_fuzzy"
                    break

        detail = {
            "investment_id": inv_id,
            "investment_name": inv_name,
            "investment_status": inv.get("status"),
            "matched_client_id": None,
            "matched_client_name": None,
            "match_method": None,
        }

        if match_client:
            detail["matched_client_id"] = match_client["id"]
            detail["matched_client_name"] = match_client["razon_social_nombre"]
            detail["match_method"] = match_method

            # Only update if not already linked
            if match_client.get("origina_investment_id") != inv_id:
                db.execute(text(
                    "UPDATE clientes SET origina_investment_id = :inv_id WHERE id = :cid"
                ), {"inv_id": inv_id, "cid": match_client["id"]})
                matched += 1

        details.append(detail)

    db.commit()

    return {
        "investments": len(investments),
        "matched": matched,
        "details": details,
    }


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
    origina_by_id: dict[int, dict] = {}
    for op in origina_projects:
        code = op.get("name") or ""
        origina_by_code[code.upper()] = op
        origina_by_id[op["id"]] = op
        parts = code.split("_", 1)
        readable = parts[1].replace("_", " ").lower() if len(parts) > 1 else code.lower()
        if readable:
            origina_by_norm[readable] = op

    supply_by_norm: dict[str, dict] = {}
    supply_by_origina_id: dict[int, dict] = {}
    for sr in requestsdb_supplies:
        name = sr.get("project_name") or ""
        norm = _normalize(name)
        if norm:
            supply_by_norm[norm] = sr
        oid = sr.get("origina_project_id")
        if oid:
            supply_by_origina_id[int(oid)] = sr

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

    # Run investment fund correlation after project correlation
    try:
        inv_result = correlate_investments(db)
    except Exception as e:
        logger.warning("Investment correlation failed: %s", e)
        inv_result = {"matched": 0, "investments": 0, "details": []}

    result = {
        "total_operations_projects": len(ops_projects),
        "origina_projects_found": len(origina_projects),
        "requestsdb_supplies_found": len(requestsdb_supplies),
        "correlations_updated": matched,
        "investment_funds_found": inv_result.get("investments", 0),
        "investment_correlations_updated": inv_result.get("matched", 0),
        "details": results,
    }

    # Log sync result
    try:
        db.execute(text(
            "INSERT INTO correlation_sync_log "
            "(synced_at, projects_processed, correlations_updated, origina_found, requestsdb_found) "
            "VALUES (NOW(), :pp, :cu, :of, :rf)"
        ), {
            "pp": len(ops_projects),
            "cu": matched,
            "of": len(origina_projects),
            "rf": len(requestsdb_supplies),
        })
        db.commit()
    except Exception as e:
        logger.warning("Failed to log correlation sync: %s", e)
        db.rollback()

    return result


def get_project_cross_view(db: Session, proyecto_id: int) -> dict:
    """Get unified cross-database view for a single project."""
    row = db.execute(text("""
        SELECT id, nombre, codigo_tsf, alias_monitoreo,
               origina_code, requestsdb_supply_id, quoia_node_name
        FROM proyectos WHERE id = :pid
    """), {"pid": proyecto_id}).mappings().first()

    if not row:
        return {"error": "Proyecto no encontrado"}

    proj = dict(row)
    try:
        from app.services.mgs.grid_map import get_grid_info
        grid = get_grid_info(proj["nombre"] or "")
    except Exception:
        grid = None

    result = {
        "proyecto": proj,
        "grid_info": grid,
        "origina": None,
        "origina_viabilities": None,
        "requestsdb": None,
        "requestsdb_status": None,
    }

    if proj.get("origina_code"):
        origina_projects = fetch_origina_projects()
        for op in origina_projects:
            if op.get("name") == proj["origina_code"]:
                result["origina"] = op
                viabs = fetch_origina_viabilities([op["id"]])
                result["origina_viabilities"] = viabs.get(op["id"], [])
                break

    if proj.get("requestsdb_supply_id"):
        sid = proj["requestsdb_supply_id"]
        supplies = fetch_requestsdb_supplies()
        for sr in supplies:
            if sr.get("supply_id") == sid:
                result["requestsdb"] = sr
                break
        statuses = fetch_requestsdb_status_history([sid])
        result["requestsdb_status"] = statuses.get(sid, [])

    return result


def get_pipeline_overview() -> dict:
    """Get pipeline overview from originabotdb — stages, counts, capacity."""
    with _origina_conn() as conn:
        if conn is None:
            return {"available": False}
        try:
            cur = conn.execute("""
                SELECT stage, COUNT(*) as count,
                       SUM(project_installed_power) AS total_kw_ac,
                       SUM(project_dc_capacity) AS total_kw_dc,
                       SUM(project_panels_count) AS total_panels
                FROM minifarm_project
                GROUP BY stage
                ORDER BY count DESC
            """)
            cols = [d.name for d in cur.description]
            stages = [dict(zip(cols, row)) for row in cur.fetchall()]

            cur2 = conn.execute("""
                SELECT go.code, go.name, COUNT(*) as count
                FROM minifarm_project mp
                LEFT JOIN grid_operator_request_gridoperator go ON mp.grid_operator_id = go.code
                WHERE mp.stage IN ('operation', 'construction', 'deploy', 'signed')
                GROUP BY go.code, go.name
                ORDER BY count DESC
            """)
            cols2 = [d.name for d in cur2.description]
            operators = [dict(zip(cols2, row)) for row in cur2.fetchall()]

            return {
                "available": True,
                "stages": stages,
                "grid_operators": operators,
                "total_projects": sum(s["count"] for s in stages),
            }
        except Exception as e:
            logger.error("pipeline overview failed: %s", e)
            return {"available": False, "error": str(e)}
