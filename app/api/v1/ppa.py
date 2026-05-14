from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import PPAContrato, PPATarifa, PPACompromisoEnergia, Proyecto
from app.models.clientes import Cliente
from app.models.contratos import ppa_contrato_proyectos_table
from app.schemas.ppa import (
    PPAContratoCreate, PPAContratoUpdate, PPAContratoOut,
    PPATarifaIn, PPATarifaOut,
    PPACompromisoIn, PPACompromisoOut,
)

router = APIRouter(prefix="/ppa", tags=["PPA"])


def _load_options():
    return [
        selectinload(PPAContrato.proyectos),
        selectinload(PPAContrato.comprador),
        selectinload(PPAContrato.vendedor),
        selectinload(PPAContrato.tarifas),
        selectinload(PPAContrato.compromisos_energia),
    ]


def _sync_partes_from_clientes(contrato: PPAContrato, db: Session):
    """Si hay comprador_id/vendedor_id, sincroniza nombre y NIT desde el cliente."""
    if contrato.comprador_id:
        c = db.query(Cliente).filter(Cliente.id == contrato.comprador_id).first()
        if c:
            contrato.comprador_nombre = c.razon_social_nombre
            contrato.comprador_nit = c.nit_cedula
    if contrato.vendedor_id:
        v = db.query(Cliente).filter(Cliente.id == contrato.vendedor_id).first()
        if v:
            contrato.vendedor_nombre = v.razon_social_nombre
            contrato.vendedor_nit = v.nit_cedula


def _get_contrato_or_404(id: int, db: Session) -> PPAContrato:
    c = db.query(PPAContrato).options(*_load_options()).filter(PPAContrato.id == id).first()
    if not c:
        raise HTTPException(404, "Contrato PPA no encontrado")
    return c


def _set_proyectos(contrato: PPAContrato, proyecto_ids: list[int], db: Session):
    proyectos = db.query(Proyecto).filter(Proyecto.id.in_(proyecto_ids)).all() if proyecto_ids else []
    contrato.proyectos = proyectos


@router.get("", response_model=list[PPAContratoOut])
def list_contratos(
    proyecto_id: int | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(PPAContrato).options(*_load_options())
    if proyecto_id is not None:
        query = query.join(
            ppa_contrato_proyectos_table,
            PPAContrato.id == ppa_contrato_proyectos_table.c.contrato_id
        ).filter(ppa_contrato_proyectos_table.c.proyecto_id == proyecto_id)
    if q:
        like = f"%{q}%"
        query = query.join(
            ppa_contrato_proyectos_table,
            PPAContrato.id == ppa_contrato_proyectos_table.c.contrato_id,
            isouter=True,
        ).join(
            Proyecto,
            ppa_contrato_proyectos_table.c.proyecto_id == Proyecto.id,
            isouter=True,
        ).filter(
            Proyecto.nombre_comercial.ilike(like)
            | PPAContrato.nombre_interno.ilike(like)
            | PPAContrato.numero_codigo_contrato.ilike(like)
            | PPAContrato.comprador_nombre.ilike(like)
        ).distinct()
    return (
        query
        .order_by(PPAContrato.fecha_inicio.desc().nullslast(), PPAContrato.id.desc())
        .all()
    )


@router.post("", response_model=PPAContratoOut, status_code=201)
def create_contrato(
    data: PPAContratoCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    payload = data.model_dump(exclude={"proyecto_ids"})
    contrato = PPAContrato(**payload)
    db.add(contrato)
    db.flush()
    _set_proyectos(contrato, data.proyecto_ids, db)
    _sync_partes_from_clientes(contrato, db)
    db.commit()
    return _get_contrato_or_404(contrato.id, db)


@router.get("/partes")
def get_partes(db: Session = Depends(get_db), _=Depends(get_current_user)):
    compradores = (
        db.query(PPAContrato.comprador_nombre, PPAContrato.comprador_nit)
        .filter(PPAContrato.comprador_nombre.isnot(None))
        .distinct()
        .all()
    )
    vendedores = (
        db.query(PPAContrato.vendedor_nombre, PPAContrato.vendedor_nit)
        .filter(PPAContrato.vendedor_nombre.isnot(None))
        .distinct()
        .all()
    )
    return {
        "compradores": [{"nombre": r.comprador_nombre, "nit": r.comprador_nit} for r in compradores],
        "vendedores": [{"nombre": r.vendedor_nombre, "nit": r.vendedor_nit} for r in vendedores],
    }


@router.get("/{id}", response_model=PPAContratoOut)
def get_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_contrato_or_404(id, db)


@router.patch("/{id}", response_model=PPAContratoOut)
def update_contrato(
    id: int,
    data: PPAContratoUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_contrato_or_404(id, db)
    update_data = data.model_dump(exclude_unset=True, exclude={"proyecto_ids"})
    for k, v in update_data.items():
        setattr(contrato, k, v)
    if data.proyecto_ids is not None:
        _set_proyectos(contrato, data.proyecto_ids, db)
    _sync_partes_from_clientes(contrato, db)
    db.commit()
    return _get_contrato_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    contrato = _get_contrato_or_404(id, db)
    db.delete(contrato)
    db.commit()


@router.put("/{id}/tarifas", response_model=list[PPATarifaOut])
def replace_tarifas(
    id: int,
    rows: list[PPATarifaIn],
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_contrato_or_404(id, db)
    db.query(PPATarifa).filter(PPATarifa.contrato_id == id).delete()
    db.add_all([PPATarifa(contrato_id=id, **r.model_dump()) for r in rows])
    db.commit()
    return db.query(PPATarifa).filter(PPATarifa.contrato_id == id).order_by(PPATarifa.año, PPATarifa.mes).all()


@router.put("/{id}/compromisos", response_model=list[PPACompromisoOut])
def replace_compromisos(
    id: int,
    rows: list[PPACompromisoIn],
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_contrato_or_404(id, db)
    db.query(PPACompromisoEnergia).filter(PPACompromisoEnergia.contrato_id == id).delete()
    db.add_all([PPACompromisoEnergia(contrato_id=id, **r.model_dump()) for r in rows])
    db.commit()
    return (
        db.query(PPACompromisoEnergia)
        .filter(PPACompromisoEnergia.contrato_id == id)
        .order_by(PPACompromisoEnergia.año, PPACompromisoEnergia.mes)
        .all()
    )
