from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.contratos import ContratoServicio, PagoServicio
from app.models.clientes import Cliente
from app.schemas.contratos_servicio import (
    ContratoServicioCreate, ContratoServicioUpdate, ContratoServicioOut,
    PagoServicioCreate, PagoServicioUpdate, PagoServicioOut,
)

router = APIRouter(prefix="/contratos-servicio", tags=["ContratoServicio"])


def _load_options():
    return [
        selectinload(ContratoServicio.contratante),
        selectinload(ContratoServicio.prestador),
    ]


def _get_or_404(id: int, db: Session) -> ContratoServicio:
    c = db.query(ContratoServicio).options(*_load_options()).filter(ContratoServicio.id == id).first()
    if not c:
        raise HTTPException(404, "Contrato no encontrado")
    return c


def _sync_partes(contrato: ContratoServicio, db: Session):
    if contrato.contratante_id:
        cl = db.query(Cliente).filter(Cliente.id == contrato.contratante_id).first()
        if cl:
            contrato.contratante_nombre = cl.razon_social_nombre
            contrato.contratante_nit = cl.nit_cedula
    if contrato.prestador_id:
        pr = db.query(Cliente).filter(Cliente.id == contrato.prestador_id).first()
        if pr:
            contrato.prestador_nombre = pr.razon_social_nombre
            contrato.prestador_nit = pr.nit_cedula


@router.get("", response_model=list[ContratoServicioOut])
def list_contratos(
    tipo: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(ContratoServicio).options(*_load_options())
    if tipo:
        q = q.filter(ContratoServicio.servicio_aplica == tipo)
    if proyecto_id:
        q = q.filter(ContratoServicio.proyecto_id == proyecto_id)
    return q.order_by(ContratoServicio.fecha_inicio.desc().nullslast(), ContratoServicio.id.desc()).limit(limit).all()


@router.post("", response_model=ContratoServicioOut, status_code=201)
def create_contrato(
    data: ContratoServicioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = ContratoServicio(**data.model_dump())
    db.add(contrato)
    db.flush()
    _sync_partes(contrato, db)
    db.commit()
    return _get_or_404(contrato.id, db)


@router.get("/{id}", response_model=ContratoServicioOut)
def get_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_or_404(id, db)


@router.patch("/{id}", response_model=ContratoServicioOut)
def update_contrato(
    id: int,
    data: ContratoServicioUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_or_404(id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(contrato, k, v)
    _sync_partes(contrato, db)
    db.commit()
    return _get_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    contrato = _get_or_404(id, db)
    db.delete(contrato)
    db.commit()


# ── Pagos de servicio ──────────────────────────────────────────────────────────

@router.get("/{id}/pagos", response_model=list[PagoServicioOut])
def list_pagos(
    id: int,
    año: int | None = Query(None),
    mes: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    q = db.query(PagoServicio).filter(PagoServicio.contrato_id == id)
    if año is not None:
        q = q.filter(PagoServicio.año == año)
    if mes is not None:
        q = q.filter(PagoServicio.mes == mes)
    return q.order_by(PagoServicio.año.desc(), PagoServicio.mes.desc()).all()


@router.post("/{id}/pagos", response_model=PagoServicioOut, status_code=201)
def create_pago(
    id: int,
    data: PagoServicioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    pago = PagoServicio(contrato_id=id, **data.model_dump())
    db.add(pago)
    db.commit()
    db.refresh(pago)
    return pago


@router.patch("/{id}/pagos/{pago_id}", response_model=PagoServicioOut)
def update_pago(
    id: int,
    pago_id: int,
    data: PagoServicioUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    pago = db.query(PagoServicio).filter(PagoServicio.id == pago_id, PagoServicio.contrato_id == id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(pago, k, v)
    db.commit()
    db.refresh(pago)
    return pago


@router.delete("/{id}/pagos/{pago_id}", status_code=204)
def delete_pago(
    id: int,
    pago_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    pago = db.query(PagoServicio).filter(PagoServicio.id == pago_id, PagoServicio.contrato_id == id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    db.delete(pago)
    db.commit()
