import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import PPAContrato, PPATarifa, PPACompromisoEnergia, Proyecto

logger = logging.getLogger(__name__)
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
    tipo_contrato: str | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(PPAContrato).filter(PPAContrato.deleted_at.is_(None)).options(*_load_options())
    if tipo_contrato is not None:
        query = query.filter(PPAContrato.tipo_contrato == tipo_contrato)
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
        .limit(limit)
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


def _compute_visibility(contrato: PPAContrato, db: Session) -> dict:
    """Compute estado_cumplimiento, dias_restantes, cobertura_actual_pct for a PPA contract."""
    today = date.today()
    result: dict = {}

    # dias_restantes
    if contrato.fecha_fin:
        result["dias_restantes"] = (contrato.fecha_fin - today).days
    else:
        result["dias_restantes"] = None

    # cobertura_actual_pct: current month gen / commitment as %
    compromiso = (
        db.query(PPACompromisoEnergia)
        .filter(
            PPACompromisoEnergia.contrato_id == contrato.id,
            PPACompromisoEnergia.año == today.year,
            PPACompromisoEnergia.mes == today.month,
        )
        .first()
    )
    min_mwh = float(compromiso.energia_minima) if compromiso and compromiso.energia_minima is not None else None

    # Try to get actual generation from cumplimiento_mensual
    from app.models.cumplimiento import CumplimientoMensual
    cumpl = (
        db.query(CumplimientoMensual)
        .filter(
            CumplimientoMensual.contrato_ppa_id == contrato.id,
            CumplimientoMensual.anio == today.year,
            CumplimientoMensual.mes == today.month,
        )
        .first()
    )
    gen_mwh = float(cumpl.gen_total_mwh) if cumpl and cumpl.gen_total_mwh is not None else None

    if min_mwh and min_mwh > 0 and gen_mwh is not None:
        result["cobertura_actual_pct"] = round(gen_mwh / min_mwh * 100, 1)
    else:
        result["cobertura_actual_pct"] = None

    # estado_cumplimiento
    if result["cobertura_actual_pct"] is not None:
        if result["cobertura_actual_pct"] >= 100:
            result["estado_cumplimiento"] = "on_track"
        elif result["cobertura_actual_pct"] >= 80:
            result["estado_cumplimiento"] = "at_risk"
        else:
            result["estado_cumplimiento"] = "deficit"
    elif contrato.fecha_fin and contrato.fecha_fin < today:
        result["estado_cumplimiento"] = "deficit"
    else:
        result["estado_cumplimiento"] = None

    return result


@router.get("/resumen-global")
def get_resumen_global(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Portfolio-level PPA summary with aggregated visibility metrics."""
    today = date.today()
    contratos = (
        db.query(PPAContrato)
        .filter(PPAContrato.deleted_at.is_(None))
        .options(*_load_options())
        .all()
    )

    total_contratos = len(contratos)
    vigentes = [c for c in contratos if c.fecha_fin and c.fecha_fin >= today]
    vencidos = [c for c in contratos if c.fecha_fin and c.fecha_fin < today]
    sin_fecha = [c for c in contratos if not c.fecha_fin]

    # Compute visibility per contract
    on_track = 0
    at_risk = 0
    deficit = 0
    sin_datos = 0
    contratos_resumen = []
    for c in contratos:
        vis = _compute_visibility(c, db)
        estado = vis.get("estado_cumplimiento")
        if estado == "on_track":
            on_track += 1
        elif estado == "at_risk":
            at_risk += 1
        elif estado == "deficit":
            deficit += 1
        else:
            sin_datos += 1

        contratos_resumen.append({
            "id": c.id,
            "nombre_interno": c.nombre_interno,
            "numero_codigo_contrato": c.numero_codigo_contrato,
            "comprador_nombre": c.comprador_nombre,
            "tipo_contrato": c.tipo_contrato,
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else None,
            "estado_cumplimiento": vis.get("estado_cumplimiento"),
            "dias_restantes": vis.get("dias_restantes"),
            "cobertura_actual_pct": vis.get("cobertura_actual_pct"),
        })

    return {
        "total_contratos": total_contratos,
        "vigentes": len(vigentes),
        "vencidos": len(vencidos),
        "sin_fecha_fin": len(sin_fecha),
        "cumplimiento": {
            "on_track": on_track,
            "at_risk": at_risk,
            "deficit": deficit,
            "sin_datos": sin_datos,
        },
        "contratos": contratos_resumen,
    }


@router.get("/{id}", response_model=PPAContratoOut)
def get_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = _get_contrato_or_404(id, db)
    out = PPAContratoOut.model_validate(c, from_attributes=True)
    vis = _compute_visibility(c, db)
    out.estado_cumplimiento = vis.get("estado_cumplimiento")
    out.dias_restantes = vis.get("dias_restantes")
    out.cobertura_actual_pct = vis.get("cobertura_actual_pct")
    return out


@router.patch("/{id}")
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
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Error al guardar contrato PPA %s", id)
        raise HTTPException(500, detail=f"Error al guardar: {e}")
    try:
        updated = _get_contrato_or_404(id, db)
        return PPAContratoOut.model_validate(updated, from_attributes=True).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error al serializar contrato PPA %s después de update", id)
        raise HTTPException(500, detail=f"Error al serializar respuesta: {e}")


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
