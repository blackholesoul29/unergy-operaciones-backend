"""Cross-database project correlation endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.services.correlation import (
    correlate_projects, get_project_cross_view, get_pipeline_overview,
    fetch_origina_investments, correlate_investments,
)

router = APIRouter(prefix="/correlation", tags=["Correlation"])


@router.post("/sync")
def run_correlation(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return correlate_projects(db)


@router.get("/status")
def correlation_status(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Last correlation sync time, result, and project counts."""
    row = db.execute(text("""
        SELECT id, synced_at, projects_processed, correlations_updated,
               origina_found, requestsdb_found, error
        FROM correlation_sync_log
        ORDER BY synced_at DESC
        LIMIT 1
    """)).first()
    if not row:
        return {
            "last_sync": None,
            "status": "never_run",
            "projects_processed": 0,
            "correlations_updated": 0,
        }
    r = dict(row._mapping)
    return {
        "last_sync": r["synced_at"].isoformat() if r["synced_at"] else None,
        "status": "error" if r.get("error") else "ok",
        "projects_processed": r["projects_processed"],
        "correlations_updated": r["correlations_updated"],
        "origina_found": r["origina_found"],
        "requestsdb_found": r["requestsdb_found"],
        "error": r.get("error"),
    }


@router.get("/project/{proyecto_id}")
def project_cross_view(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return get_project_cross_view(db, proyecto_id)


@router.get("/pipeline")
def pipeline_overview(_=Depends(get_current_user)):
    return get_pipeline_overview()


# ── Investment fund correlation ─────────────────────────────────────────────


@router.get("/fondos")
def list_investment_funds(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List all investment funds from origina with their matched operations client."""
    investments = fetch_origina_investments()

    # Build lookup: origina_investment_id -> client
    linked_rows = db.execute(text(
        "SELECT id, razon_social_nombre, origina_investment_id "
        "FROM clientes "
        "WHERE origina_investment_id IS NOT NULL AND deleted_at IS NULL"
    )).mappings().all()
    linked_by_inv_id: dict[int, dict] = {
        r["origina_investment_id"]: {"id": r["id"], "razon_social_nombre": r["razon_social_nombre"]}
        for r in linked_rows
    }

    results = []
    for inv in investments:
        inv_id = inv["id"]
        linked_client = linked_by_inv_id.get(inv_id)
        results.append({
            "id": inv_id,
            "code": inv.get("code"),
            "name": inv.get("name"),
            "email": inv.get("email"),
            "phone": inv.get("phone"),
            "status": inv.get("status"),
            "rut": inv.get("rut"),
            "portfolio_count": inv.get("portfolio_count", 0),
            "minifarm_count": inv.get("minifarm_count", 0),
            "total_kw": float(inv.get("total_kw") or 0),
            "match_status": "matched" if linked_client else "unmatched",
            "linked_client": linked_client,
        })

    return {
        "total": len(results),
        "matched": sum(1 for r in results if r["match_status"] == "matched"),
        "unmatched": sum(1 for r in results if r["match_status"] == "unmatched"),
        "items": results,
    }


@router.post("/fondos/sync")
def sync_investment_funds(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Run investment fund correlation (auto-match funds to clients)."""
    return correlate_investments(db)


@router.post("/fondos/{inv_id}/vincular/{cliente_id}")
def link_fund_to_client(
    inv_id: int,
    cliente_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Manually link an investment fund to a client."""
    # Verify client exists
    client_row = db.execute(text(
        "SELECT id, razon_social_nombre FROM clientes WHERE id = :cid AND deleted_at IS NULL"
    ), {"cid": cliente_id}).mappings().first()
    if not client_row:
        raise HTTPException(404, "Cliente no encontrado")

    # Verify fund exists in origina
    investments = fetch_origina_investments()
    fund = next((i for i in investments if i["id"] == inv_id), None)
    if not fund:
        raise HTTPException(404, "Fondo de inversión no encontrado en Origina")

    # Check if another client is already linked to this fund
    existing = db.execute(text(
        "SELECT id, razon_social_nombre FROM clientes "
        "WHERE origina_investment_id = :inv_id AND id != :cid AND deleted_at IS NULL"
    ), {"inv_id": inv_id, "cid": cliente_id}).mappings().first()
    if existing:
        raise HTTPException(
            409,
            f"Este fondo ya está vinculado al cliente '{existing['razon_social_nombre']}' (id={existing['id']})"
        )

    db.execute(text(
        "UPDATE clientes SET origina_investment_id = :inv_id WHERE id = :cid"
    ), {"inv_id": inv_id, "cid": cliente_id})
    db.commit()

    return {
        "status": "linked",
        "investment_id": inv_id,
        "investment_name": fund.get("name"),
        "cliente_id": cliente_id,
        "cliente_nombre": client_row["razon_social_nombre"],
    }


@router.delete("/fondos/{inv_id}/desvincular")
def unlink_fund(
    inv_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Remove the link between an investment fund and its client."""
    result = db.execute(text(
        "UPDATE clientes SET origina_investment_id = NULL "
        "WHERE origina_investment_id = :inv_id AND deleted_at IS NULL"
    ), {"inv_id": inv_id})
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "No se encontró cliente vinculado a este fondo")
    return {"status": "unlinked", "investment_id": inv_id}
