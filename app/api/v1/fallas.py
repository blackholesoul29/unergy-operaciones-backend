from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import (
    Falla, FallaSeguimiento,
    FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria, FallaCatResolucion,
)
from app.models.usuarios import Usuario
from app.schemas.fallas import (
    FallaCreate, FallaUpdate, FallaOut,
    FallaSeguimientoCreate, FallaSeguimientoOut,
    FallaCatalogos, FallaCatEstadoOut, FallaCatPrioridadOut, FallaCatTipoOut, FallaCatResolucionOut,
)
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/fallas", tags=["Fallas"])

_FALLA_LOAD = [
    selectinload(Falla.proyecto),
    selectinload(Falla.tipo).selectinload(FallaCatTipo.categoria),
    selectinload(Falla.estado),
    selectinload(Falla.prioridad),
    selectinload(Falla.resolucion),
    selectinload(Falla.registrado_por),
    selectinload(Falla.asignado_a),
    selectinload(Falla.seguimientos).selectinload(FallaSeguimiento.usuario),
    selectinload(Falla.seguimientos).selectinload(FallaSeguimiento.estado_nuevo),
]


def _get_or_404(id: int, db: Session) -> Falla:
    falla = db.query(Falla).options(*_FALLA_LOAD).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    return falla


def _gen_codigo(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.query(func.count(Falla.id)).scalar() or 0
    return f"FAL-{year}-{count + 1:05d}"


@router.get("/catalogos", response_model=FallaCatalogos)
def get_catalogos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    estados = db.query(FallaCatEstado).order_by(FallaCatEstado.orden).all()
    prioridades = db.query(FallaCatPrioridad).order_by(FallaCatPrioridad.nivel).all()
    tipos = (
        db.query(FallaCatTipo)
        .options(selectinload(FallaCatTipo.categoria))
        .filter(FallaCatTipo.activa == True)
        .order_by(FallaCatTipo.etiqueta)
        .all()
    )
    resoluciones = db.query(FallaCatResolucion).order_by(FallaCatResolucion.etiqueta).all()
    return {"estados": estados, "prioridades": prioridades, "tipos": tipos, "resoluciones": resoluciones}


@router.get("", response_model=PaginatedResponse[FallaOut])
def list_fallas(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    estado_id: int | None = None,
    prioridad_id: int | None = None,
    proyecto_id: int | None = None,
    asignado_a_id: int | None = None,
    codigo_legado: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(Falla).options(*_FALLA_LOAD)
    if q:
        query = query.filter(Falla.descripcion.ilike(f"%{q}%") | Falla.codigo_interno.ilike(f"%{q}%"))
    if estado_id:
        query = query.filter(Falla.estado_id == estado_id)
    if prioridad_id:
        query = query.filter(Falla.prioridad_id == prioridad_id)
    if proyecto_id:
        query = query.filter(Falla.proyecto_id == proyecto_id)
    if asignado_a_id:
        query = query.filter(Falla.asignado_a_id == asignado_a_id)
    if codigo_legado:
        query = query.filter(Falla.codigo_legado == codigo_legado)
    total = query.count()
    items = query.order_by(Falla.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.post("", response_model=FallaOut, status_code=201)
def create_falla(
    data: FallaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    falla = Falla(
        **data.model_dump(),
        codigo_interno=_gen_codigo(db),
        registrado_por_id=current_user.id,
    )
    db.add(falla)
    db.commit()
    return _get_or_404(falla.id, db)


@router.get("/{id}", response_model=FallaOut)
def get_falla(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_or_404(id, db)


@router.patch("/{id}", response_model=FallaOut)
def update_falla(
    id: int,
    data: FallaUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(falla, k, v)
    db.commit()
    return _get_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_falla(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    db.delete(falla)
    db.commit()


@router.post("/{id}/seguimientos", response_model=FallaSeguimientoOut, status_code=201)
def add_seguimiento(
    id: int,
    data: FallaSeguimientoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")

    seg = FallaSeguimiento(
        falla_id=id,
        usuario_id=current_user.id,
        nota=data.nota,
        estado_nuevo_id=data.estado_nuevo_id,
    )
    if data.estado_nuevo_id:
        falla.estado_id = data.estado_nuevo_id

    db.add(seg)
    db.commit()
    db.refresh(seg)

    return (
        db.query(FallaSeguimiento)
        .options(
            selectinload(FallaSeguimiento.usuario),
            selectinload(FallaSeguimiento.estado_nuevo),
        )
        .filter(FallaSeguimiento.id == seg.id)
        .first()
    )
