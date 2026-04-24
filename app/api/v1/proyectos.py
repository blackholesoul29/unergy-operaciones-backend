from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Proyecto
from app.models.proyectos import ProyectoInversionista
from app.schemas.proyectos import (
    ProyectoCreate, ProyectoUpdate, ProyectoOut,
    ProyectoInversionistaCreate, ProyectoInversionistaOut,
)
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/proyectos", tags=["Proyectos"])


def _get_proyecto_or_404(id: int, db: Session) -> Proyecto:
    p = db.query(Proyecto).options(
        selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente)
    ).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


@router.get("", response_model=PaginatedResponse[ProyectoOut])
def list_proyectos(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    estado: str | None = None,
    tipo_proyecto: str | None = None,
    cliente_id: int | None = None,
    portafolio_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Proyecto).options(
        selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente)
    )
    if q:
        query = query.filter(Proyecto.nombre_comercial.ilike(f"%{q}%"))
    if estado:
        query = query.filter(Proyecto.estado == estado)
    if tipo_proyecto:
        query = query.filter(Proyecto.tipo_proyecto == tipo_proyecto)
    if cliente_id:
        query = query.filter(Proyecto.cliente_id == cliente_id)
    if portafolio_id:
        query = query.filter(Proyecto.portafolio_id == portafolio_id)
    total = query.count()
    items = query.order_by(Proyecto.nombre_comercial).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.post("", response_model=ProyectoOut, status_code=201)
def create_proyecto(data: ProyectoCreate, db: Session = Depends(get_db)):
    proyecto = Proyecto(**data.model_dump())
    db.add(proyecto)
    db.commit()
    return _get_proyecto_or_404(proyecto.id, db)


@router.get("/{id}", response_model=ProyectoOut)
def get_proyecto(id: int, db: Session = Depends(get_db)):
    return _get_proyecto_or_404(id, db)


@router.patch("/{id}", response_model=ProyectoOut)
def update_proyecto(id: int, data: ProyectoUpdate, db: Session = Depends(get_db)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return _get_proyecto_or_404(id, db)


@router.patch("/{id}/servicios", response_model=ProyectoOut)
def toggle_servicios(id: int, data: dict, db: Session = Depends(get_db)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    allowed = {"srv_operacion", "srv_representacion", "srv_cgm", "srv_ppa", "srv_promotor", "srv_rec"}
    for k, v in data.items():
        if k in allowed:
            setattr(p, k, v)
    db.commit()
    return _get_proyecto_or_404(id, db)


# ── Inversionistas ────────────────────────────────────────────────────────────

@router.get("/{id}/inversionistas", response_model=list[ProyectoInversionistaOut])
def list_inversionistas(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    return (
        db.query(ProyectoInversionista)
        .options(selectinload(ProyectoInversionista.cliente))
        .filter(ProyectoInversionista.proyecto_id == id)
        .all()
    )


@router.post("/{id}/inversionistas", response_model=ProyectoInversionistaOut, status_code=201)
def add_inversionista(id: int, data: ProyectoInversionistaCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    duplicate = db.query(ProyectoInversionista).filter_by(
        proyecto_id=id, cliente_id=data.cliente_id
    ).first()
    if duplicate:
        raise HTTPException(409, "Este cliente ya es inversionista de este proyecto")
    inv = ProyectoInversionista(proyecto_id=id, **data.model_dump())
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return db.query(ProyectoInversionista).options(
        selectinload(ProyectoInversionista.cliente)
    ).filter(ProyectoInversionista.id == inv.id).first()


@router.delete("/{id}/inversionistas/{inv_id}", status_code=204)
def remove_inversionista(id: int, inv_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    inv = db.query(ProyectoInversionista).filter_by(id=inv_id, proyecto_id=id).first()
    if not inv:
        raise HTTPException(404, "Inversionista no encontrado")
    db.delete(inv)
    db.commit()
