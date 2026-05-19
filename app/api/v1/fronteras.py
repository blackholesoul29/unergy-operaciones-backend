from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera
from app.schemas.fronteras import FronteraCreate, FronteraOut
from app.services.mgs.quoia_client import QuoiaClient

router = APIRouter(prefix="/fronteras", tags=["Fronteras"])

_quoia: QuoiaClient | None = None


def _get_quoia() -> QuoiaClient:
    global _quoia
    if _quoia is None:
        _quoia = QuoiaClient()
    if not _quoia.enabled:
        raise HTTPException(503, "QUOIA_API_TOKEN not configured")
    return _quoia


def _to_out(f: Frontera) -> FronteraOut:
    d = FronteraOut.model_validate(f)
    if f.proyecto:
        d.proyecto_nombre = f.proyecto.nombre_comercial
    return d


@router.get("", response_model=list[FronteraOut])
def list_fronteras(
    proyecto_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Frontera).options(joinedload(Frontera.proyecto))
    if proyecto_id:
        q = q.filter(Frontera.proyecto_id == proyecto_id)
    return [_to_out(f) for f in q.order_by(Frontera.codigo_frontera).all()]


@router.post("", response_model=FronteraOut, status_code=201)
def create_frontera(
    body: FronteraCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if body.codigo_frontera:
        existing = db.query(Frontera).filter_by(codigo_frontera=body.codigo_frontera).first()
        if existing:
            for k, v in body.model_dump(exclude_none=True).items():
                setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return _to_out(db.query(Frontera).options(joinedload(Frontera.proyecto)).filter(Frontera.id == existing.id).first())
    obj = Frontera(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _to_out(db.query(Frontera).options(joinedload(Frontera.proyecto)).filter(Frontera.id == obj.id).first())


@router.get("/quoia/meters")
def quoia_meters(
    search: str = Query("", description="Filter meters by name"),
    _=Depends(get_current_user),
):
    """All Quoia smart meters (300 total)."""
    client = _get_quoia()
    meters = client.get_meters(search=search)
    stats = {"total": len(meters)}
    for m in meters:
        name = (m.get("name") or "").lower()
        if name.startswith("mgs"):
            stats["mgs"] = stats.get("mgs", 0) + 1
        elif name.startswith("minigranja"):
            stats["minigranja"] = stats.get("minigranja", 0) + 1
        elif name.startswith("gd"):
            stats["gd"] = stats.get("gd", 0) + 1
    return {"stats": stats, "meters": meters}


@router.get("/quoia/meters/{meter_id}/curves")
def quoia_meter_curves(meter_id: int, _=Depends(get_current_user)):
    """Typical consumption/generation curves for a meter (7 weekdays × 96 points)."""
    client = _get_quoia()
    curves = client.get_typical_curves(node_id=meter_id)
    if not curves:
        return {"meter_id": meter_id, "curves": []}

    summary = []
    for c in curves:
        iae = c.get("iae", [])
        eae = c.get("eae", [])
        summary.append({
            "weekday": c.get("weekday"),
            "quality_score": c.get("quality_score"),
            "days_used": c.get("days_used"),
            "total_import_kwh": round(sum(iae), 2) if iae else 0,
            "total_export_kwh": round(sum(eae), 2) if eae else 0,
            "iae": iae,
            "eae": eae,
        })
    return {"meter_id": meter_id, "curves": summary}
