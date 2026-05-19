"""Cross-database project correlation endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.services.correlation import correlate_projects, get_project_cross_view

router = APIRouter(prefix="/correlation", tags=["Correlation"])


@router.post("/sync")
def run_correlation(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return correlate_projects(db)


@router.get("/project/{proyecto_id}")
def project_cross_view(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return get_project_cross_view(db, proyecto_id)
