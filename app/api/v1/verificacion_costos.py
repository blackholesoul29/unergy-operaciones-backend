from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.verificacion_costos import VerificacionCosto
from app.models.proyectos import Proyecto
from app.schemas.verificacion_costos import (
    VerificacionCostoOut, VerificacionCostoCreate, VerificacionCostoUpdate,
)

router = APIRouter(prefix="/verificacion-costos", tags=["Verificación de costos"])


def _out(v: VerificacionCosto, nombre: str | None) -> VerificacionCostoOut:
    d = VerificacionCostoOut.model_validate(v)
    d.proyecto_nombre = nombre or ""
    return d


@router.get("", response_model=list[VerificacionCostoOut])
def list_verificacion(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = (
        db.query(VerificacionCosto, Proyecto.nombre_comercial)
        .join(Proyecto, Proyecto.id == VerificacionCosto.proyecto_id)
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return [_out(v, nombre) for v, nombre in rows]


@router.post("", response_model=VerificacionCostoOut, status_code=201)
def crear_verificacion(data: VerificacionCostoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    proy = db.query(Proyecto).filter(Proyecto.id == data.proyecto_id).first()
    if not proy:
        raise HTTPException(404, "Proyecto no encontrado")
    if db.query(VerificacionCosto).filter(VerificacionCosto.proyecto_id == data.proyecto_id).first():
        raise HTTPException(409, "Ya existe una verificación de costos para este proyecto")
    v = VerificacionCosto(**data.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return _out(v, proy.nombre_comercial)


@router.patch("/{id}", response_model=VerificacionCostoOut)
def actualizar_verificacion(id: int, data: VerificacionCostoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.query(VerificacionCosto).filter(VerificacionCosto.id == id).first()
    if not v:
        raise HTTPException(404, "Verificación no encontrada")
    for k, val in data.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    db.commit()
    db.refresh(v)
    nombre = db.query(Proyecto.nombre_comercial).filter(Proyecto.id == v.proyecto_id).scalar()
    return _out(v, nombre)


@router.delete("/{id}", status_code=204)
def eliminar_verificacion(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    v = db.query(VerificacionCosto).filter(VerificacionCosto.id == id).first()
    if not v:
        raise HTTPException(404, "Verificación no encontrada")
    db.delete(v)
    db.commit()
