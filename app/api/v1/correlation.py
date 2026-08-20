"""Cross-database project correlation endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.services.correlation import (
    correlate_projects, get_project_cross_view, get_pipeline_overview,
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
