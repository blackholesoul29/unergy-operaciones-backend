from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import Proyecto
from app.schemas.proyectos import ProyectoCreate, ProyectoUpdate, ProyectoOut
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/proyectos", tags=["Proyectos"])


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
    query = db.query(Proyecto)
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
    db.refresh(proyecto)
    return proyecto


@router.get("/{id}", response_model=ProyectoOut)
def get_proyecto(id: int, db: Session = Depends(get_db)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


@router.patch("/{id}", response_model=ProyectoOut)
def update_proyecto(id: int, data: ProyectoUpdate, db: Session = Depends(get_db)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{id}/servicios", response_model=ProyectoOut)
def toggle_servicios(id: int, data: dict, db: Session = Depends(get_db)):
    """Activar/desactivar servicios de un proyecto."""
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    allowed = {"srv_operacion", "srv_representacion", "srv_cgm", "srv_ppa", "srv_promotor", "srv_rec"}
    for k, v in data.items():
        if k in allowed:
            setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p
