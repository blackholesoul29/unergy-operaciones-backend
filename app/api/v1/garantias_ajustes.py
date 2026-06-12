"""Garantías Ajustes XM — historial de ajustes semanal/TXR/mensual."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.garantias_ajustes import GarantiaAjuste
from app.schemas.garantias_ajustes import (
    GarantiaAjusteCreate,
    GarantiaAjusteUpdate,
    GarantiaAjusteOut,
)

router = APIRouter(prefix="/garantias-ajustes", tags=["Garantías Ajustes"])


def _to_out(r: GarantiaAjuste) -> dict:
    return {
        "id":    r.id,
        "tipo":  r.tipo.value if r.tipo else None,
        "fecha": r.fecha.isoformat() if r.fecha else None,
        "pb":            float(r.pb)            if r.pb            is not None else None,
        "restricciones": float(r.restricciones) if r.restricciones is not None else None,
        "stn":           float(r.stn)           if r.stn           is not None else None,
        "trm":           float(r.trm)           if r.trm           is not None else None,
        "ptb":           float(r.ptb)           if r.ptb           is not None else None,
        "total_ungc":          float(r.total_ungc)          if r.total_ungc          is not None else None,
        "total_ungg":          float(r.total_ungg)          if r.total_ungg          is not None else None,
        "total_consignar":     float(r.total_consignar)     if r.total_consignar     is not None else None,
        "disponible_custodia": float(r.disponible_custodia) if r.disponible_custodia is not None else None,
        "congelado":           float(r.congelado)           if r.congelado           is not None else None,
        "saldo":               float(r.saldo)               if r.saldo               is not None else None,
        "total_ajuste_txr":    float(r.total_ajuste_txr)    if r.total_ajuste_txr    is not None else None,
        "snapshot": r.snapshot,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
def list_ajustes(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    rows = (
        db.query(GarantiaAjuste)
        .order_by(GarantiaAjuste.fecha.desc(), GarantiaAjuste.id.desc())
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", status_code=201)
def create_ajuste(
    data: GarantiaAjusteCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    row = GarantiaAjuste(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.patch("/{ajuste_id}")
def update_ajuste(
    ajuste_id: int,
    data: GarantiaAjusteUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    row = db.query(GarantiaAjuste).filter(GarantiaAjuste.id == ajuste_id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{ajuste_id}", status_code=204)
def delete_ajuste(
    ajuste_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    row = db.query(GarantiaAjuste).filter(GarantiaAjuste.id == ajuste_id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    db.delete(row)
    db.commit()
