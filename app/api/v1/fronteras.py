from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera
from app.schemas.fronteras import FronteraCreate, FronteraOut

router = APIRouter(prefix="/fronteras", tags=["Fronteras"])


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
