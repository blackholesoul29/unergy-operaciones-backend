from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.generacion import GeneracionDiaria
from app.schemas.generacion import (
    GeneracionDiariaCreate, GeneracionDiariaUpdate,
    GeneracionDiariaOut, GeneracionDiariaBulkUpsert,
)

router = APIRouter(prefix="/generacion", tags=["Generación"])


@router.get("", response_model=list[GeneracionDiariaOut])
def list_generacion(
    proyecto_id: int | None = Query(None),
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(GeneracionDiaria)
    if proyecto_id:
        q = q.filter(GeneracionDiaria.proyecto_id == proyecto_id)
    if fecha_inicio:
        q = q.filter(GeneracionDiaria.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.filter(GeneracionDiaria.fecha <= fecha_fin)
    return q.order_by(GeneracionDiaria.proyecto_id, GeneracionDiaria.fecha).all()


@router.post("", response_model=GeneracionDiariaOut, status_code=201)
def create_generacion(
    data: GeneracionDiariaCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    existing = (
        db.query(GeneracionDiaria)
        .filter(
            GeneracionDiaria.proyecto_id == data.proyecto_id,
            GeneracionDiaria.fecha == data.fecha,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, f"Ya existe registro para proyecto {data.proyecto_id} en fecha {data.fecha}")
    row = GeneracionDiaria(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{id}", response_model=GeneracionDiariaOut)
def update_generacion(
    id: int,
    data: GeneracionDiariaUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    row = db.query(GeneracionDiaria).filter(GeneracionDiaria.id == id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{id}", status_code=204)
def delete_generacion(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    row = db.query(GeneracionDiaria).filter(GeneracionDiaria.id == id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    db.delete(row)
    db.commit()


@router.post("/bulk-upsert", response_model=dict)
def bulk_upsert_generacion(
    data: GeneracionDiariaBulkUpsert,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    inserted = 0
    updated = 0
    for item in data.datos:
        existing = (
            db.query(GeneracionDiaria)
            .filter(
                GeneracionDiaria.proyecto_id == data.proyecto_id,
                GeneracionDiaria.fecha == item.fecha,
            )
            .first()
        )
        if existing:
            for k, v in item.model_dump(exclude_none=True).items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(GeneracionDiaria(proyecto_id=data.proyecto_id, **item.model_dump()))
            inserted += 1
    db.commit()
    return {"ok": True, "inserted": inserted, "updated": updated}
