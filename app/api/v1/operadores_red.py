from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.operadores_red import OperadorRed, OperadorRedContacto
from app.models.fronteras import Frontera
from app.schemas.operadores_red import (
    OperadorRedOut, OperadorRedCreate, OperadorRedUpdate,
    OperadorRedContactoOut, OperadorRedContactoCreate, OperadorRedContactoUpdate,
)

router = APIRouter(prefix="/operadores-red", tags=["Operadores de Red"])


@router.get("", response_model=list[OperadorRedOut])
def list_operadores(db: Session = Depends(get_db), _=Depends(get_current_user)):
    operadores = db.query(OperadorRed).options(selectinload(OperadorRed.contactos)).order_by(
        OperadorRed.nombre_comercial, OperadorRed.nombre_legal
    ).all()
    conteos = dict(
        db.query(Frontera.operador_red_id, func.count(Frontera.id))
        .filter(Frontera.operador_red_id.isnot(None), Frontera.deleted_at.is_(None))
        .group_by(Frontera.operador_red_id)
        .all()
    )
    resultado = []
    for op in operadores:
        d = OperadorRedOut.model_validate(op)
        d.fronteras_vinculadas = conteos.get(op.id, 0)
        resultado.append(d)
    return resultado


@router.post("", response_model=OperadorRedOut, status_code=201)
def create_operador(
    data: OperadorRedCreate, db: Session = Depends(get_db), _=Depends(get_current_user),
):
    existente = (
        db.query(OperadorRed)
        .filter(func.lower(OperadorRed.nombre_legal) == data.nombre_legal.strip().lower())
        .first()
    )
    if existente:
        raise HTTPException(409, f"Ya existe un operador de red con ese nombre legal (ID {existente.id})")

    op = OperadorRed(**data.model_dump())
    db.add(op)
    db.commit()
    db.refresh(op)
    d = OperadorRedOut.model_validate(op)
    d.fronteras_vinculadas = 0
    return d


@router.patch("/{operador_id}", response_model=OperadorRedOut)
def update_operador(
    operador_id: int, data: OperadorRedUpdate,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    op = _get_operador_or_404(operador_id, db)
    cambios = data.model_dump(exclude_unset=True)
    if "nombre_legal" in cambios and cambios["nombre_legal"]:
        duplicado = (
            db.query(OperadorRed)
            .filter(
                func.lower(OperadorRed.nombre_legal) == cambios["nombre_legal"].strip().lower(),
                OperadorRed.id != operador_id,
            )
            .first()
        )
        if duplicado:
            raise HTTPException(409, f"Ya existe otro operador de red con ese nombre legal (ID {duplicado.id})")
    for k, v in cambios.items():
        setattr(op, k, v)
    db.commit()
    db.refresh(op)
    d = OperadorRedOut.model_validate(op)
    d.fronteras_vinculadas = (
        db.query(func.count(Frontera.id))
        .filter(Frontera.operador_red_id == operador_id, Frontera.deleted_at.is_(None))
        .scalar() or 0
    )
    return d


@router.get("/{operador_id}", response_model=OperadorRedOut)
def get_operador(operador_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    op = (
        db.query(OperadorRed)
        .options(selectinload(OperadorRed.contactos))
        .filter(OperadorRed.id == operador_id)
        .first()
    )
    if not op:
        raise HTTPException(404, "Operador de red no encontrado")
    d = OperadorRedOut.model_validate(op)
    d.fronteras_vinculadas = (
        db.query(func.count(Frontera.id))
        .filter(Frontera.operador_red_id == operador_id, Frontera.deleted_at.is_(None))
        .scalar() or 0
    )
    return d


def _get_contacto_or_404(contacto_id: int, db: Session) -> OperadorRedContacto:
    c = db.query(OperadorRedContacto).filter(OperadorRedContacto.id == contacto_id).first()
    if not c:
        raise HTTPException(404, "Contacto no encontrado")
    return c


def _get_operador_or_404(operador_id: int, db: Session) -> OperadorRed:
    op = db.query(OperadorRed).filter(OperadorRed.id == operador_id).first()
    if not op:
        raise HTTPException(404, "Operador de red no encontrado")
    return op


@router.post("/{operador_id}/contactos", response_model=OperadorRedContactoOut, status_code=201)
def add_contacto(
    operador_id: int, data: OperadorRedContactoCreate,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    _get_operador_or_404(operador_id, db)
    contacto = OperadorRedContacto(operador_red_id=operador_id, **data.model_dump())
    db.add(contacto)
    db.commit()
    db.refresh(contacto)
    return contacto


@router.patch("/contactos/{contacto_id}", response_model=OperadorRedContactoOut)
def update_contacto(
    contacto_id: int, data: OperadorRedContactoUpdate,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    contacto = _get_contacto_or_404(contacto_id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(contacto, k, v)
    db.commit()
    db.refresh(contacto)
    return contacto


@router.delete("/contactos/{contacto_id}", status_code=204)
def delete_contacto(contacto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    contacto = _get_contacto_or_404(contacto_id, db)
    db.delete(contacto)
    db.commit()
