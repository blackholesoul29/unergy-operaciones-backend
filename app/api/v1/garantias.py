"""Garantías XM — guarantee/warranty management for solar projects."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user, _require_admin
from app.core.database import get_db
from app.models.garantias import Garantia, GarantiaMovimiento, EstadoGarantiaEnum
from app.models.proyectos import Proyecto
from app.models.contratos import PPAContrato
from app.schemas.garantias import (
    GarantiaCreate, GarantiaUpdate, GarantiaOut,
    MovimientoCreate, MovimientoOut,
)
from app.services.garantias_saldo import saldos_vivos

router = APIRouter(prefix="/garantias", tags=["Garantías"])


def _garantia_to_out(g: Garantia, saldo_vivo_cop: float) -> dict:
    # `saldo_vivo_cop` es OBLIGATORIO a propósito: un default que degrade al constituido
    # convierte un call site olvidado en un número falso pero creíble — exactamente el bug
    # que este módulo existe para matar. El fallback honesto vive en `saldo_vivo()`.
    d = {
        "id": g.id,
        "proyecto_id": g.proyecto_id,
        "contrato_ppa_id": g.contrato_ppa_id,
        "codigo_frontera": g.codigo_frontera,
        "tipo": g.tipo.value if g.tipo else None,
        "entidad": g.entidad,
        "numero_referencia": g.numero_referencia,
        "valor_cop": float(g.valor_cop) if g.valor_cop is not None else 0,
        "saldo_vivo_cop": round(saldo_vivo_cop, 2),
        "porcentaje_cobertura": float(g.porcentaje_cobertura) if g.porcentaje_cobertura is not None else None,
        "fecha_constitucion": g.fecha_constitucion.isoformat() if g.fecha_constitucion else None,
        "fecha_vencimiento": g.fecha_vencimiento.isoformat() if g.fecha_vencimiento else None,
        "estado": g.estado.value if g.estado else None,
        "observaciones": g.observaciones,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        "proyecto_nombre": g.proyecto.nombre_comercial if g.proyecto else None,
        "contrato_nombre": (g.contrato_ppa.nombre_interno or g.contrato_ppa.numero_codigo_contrato) if g.contrato_ppa else None,
    }
    return d


@router.get("/resumen")
def garantias_resumen(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Dashboard summary: total balance, expiring, oversold, by type."""
    today = date.today()
    threshold_30d = today + timedelta(days=30)

    vigentes = db.query(Garantia).filter(Garantia.estado == EstadoGarantiaEnum.vigente).all()

    saldos = saldos_vivos(db, vigentes)
    total_valor = sum(float(g.valor_cop or 0) for g in vigentes)
    total_saldo_vivo = sum(saldos[g.id] for g in vigentes)
    count_vigentes = len(vigentes)

    expiring_soon = [g for g in vigentes if g.fecha_vencimiento and g.fecha_vencimiento <= threshold_30d]
    already_expired = db.query(func.count(Garantia.id)).filter(
        Garantia.estado == EstadoGarantiaEnum.vencida
    ).scalar() or 0

    # Exceso de cobertura: projects where coverage exceeds 100%
    exceso_cobertura = []
    for g in vigentes:
        if g.porcentaje_cobertura and g.porcentaje_cobertura > 100:
            exceso_cobertura.append({
                "garantia_id": g.id,
                "proyecto_nombre": g.proyecto.nombre_comercial if g.proyecto else "—",
                "porcentaje": float(g.porcentaje_cobertura),
            })

    # By type breakdown
    by_tipo = {}
    for g in vigentes:
        t = g.tipo.value if g.tipo else "otro"
        if t not in by_tipo:
            by_tipo[t] = {"count": 0, "valor_cop": 0, "saldo_vivo_cop": 0}
        by_tipo[t]["count"] += 1
        by_tipo[t]["valor_cop"] += float(g.valor_cop or 0)
        by_tipo[t]["saldo_vivo_cop"] += saldos[g.id]

    # Recent movements (last 30 days)
    recent_movs = (
        db.query(GarantiaMovimiento)
        .filter(GarantiaMovimiento.fecha >= today - timedelta(days=30))
        .order_by(GarantiaMovimiento.fecha.desc())
        .limit(10)
        .all()
    )

    return {
        "total_valor_cop": round(total_valor, 2),
        "total_saldo_vivo_cop": round(total_saldo_vivo, 2),
        "count_vigentes": count_vigentes,
        "count_vencidas": already_expired,
        "expiring_30d": [
            {
                "id": g.id,
                "proyecto_nombre": g.proyecto.nombre_comercial if g.proyecto else "—",
                "fecha_vencimiento": g.fecha_vencimiento.isoformat(),
                "valor_cop": float(g.valor_cop or 0),
                "saldo_vivo_cop": round(saldos[g.id], 2),
                "dias_restantes": (g.fecha_vencimiento - today).days,
            }
            for g in sorted(expiring_soon, key=lambda x: x.fecha_vencimiento)
        ],
        "exceso_cobertura": exceso_cobertura,
        "por_tipo": by_tipo,
        "movimientos_recientes": [
            {
                "id": m.id,
                "tipo": m.tipo.value,
                "monto_cop": float(m.monto_cop),
                "fecha": m.fecha.isoformat(),
                "concepto": m.concepto,
            }
            for m in recent_movs
        ],
    }


@router.get("")
def list_garantias(
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    proyecto_id: Optional[int] = None,
    expiring_days: Optional[int] = Query(None, ge=1, le=365),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Garantia)
    if estado:
        try:
            q = q.filter(Garantia.estado == EstadoGarantiaEnum(estado))
        except ValueError:
            raise HTTPException(400, f"Estado inválido: {estado}")
    if tipo:
        from app.models.garantias import TipoGarantiaEnum
        try:
            q = q.filter(Garantia.tipo == TipoGarantiaEnum(tipo))
        except ValueError:
            raise HTTPException(400, f"Tipo inválido: {tipo}")
    if proyecto_id:
        q = q.filter(Garantia.proyecto_id == proyecto_id)
    if expiring_days:
        cutoff = date.today() + timedelta(days=expiring_days)
        if not estado:
            q = q.filter(Garantia.estado == EstadoGarantiaEnum.vigente)
        q = q.filter(
            Garantia.fecha_vencimiento.isnot(None),
            Garantia.fecha_vencimiento <= cutoff,
        )
    garantias = q.order_by(Garantia.fecha_vencimiento.nullslast(), Garantia.id).all()
    saldos = saldos_vivos(db, garantias)
    return {
        "items": [_garantia_to_out(g, saldos[g.id]) for g in garantias],
        "total": len(garantias),
    }


@router.get("/vencimientos-proximos")
def vencimientos_proximos(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Warranties expiring within the next N days (default 30). Groups by 30/60/90 day buckets."""
    today = date.today()
    cutoff = today + timedelta(days=dias)

    garantias = (
        db.query(Garantia)
        .filter(
            Garantia.estado == EstadoGarantiaEnum.vigente,
            Garantia.fecha_vencimiento.isnot(None),
            Garantia.fecha_vencimiento <= cutoff,
            Garantia.fecha_vencimiento >= today,
        )
        .order_by(Garantia.fecha_vencimiento)
        .all()
    )

    saldos = saldos_vivos(db, garantias)

    # Group by 30/60/90 day buckets
    buckets = {"30_dias": [], "60_dias": [], "90_dias": []}
    for g in garantias:
        dias_restantes = (g.fecha_vencimiento - today).days
        item = {
            "id": g.id,
            "proyecto_nombre": g.proyecto.nombre_comercial if g.proyecto else None,
            "contrato_nombre": (g.contrato_ppa.nombre_interno or g.contrato_ppa.numero_codigo_contrato) if g.contrato_ppa else None,
            "tipo": g.tipo.value if g.tipo else None,
            "entidad": g.entidad,
            "valor_cop": float(g.valor_cop or 0),
            "saldo_vivo_cop": round(saldos[g.id], 2),
            "fecha_vencimiento": g.fecha_vencimiento.isoformat(),
            "dias_restantes": dias_restantes,
        }
        if dias_restantes <= 30:
            buckets["30_dias"].append(item)
        elif dias_restantes <= 60:
            buckets["60_dias"].append(item)
        else:
            buckets["90_dias"].append(item)

    return {
        "total": len(garantias),
        "valor_total_cop": round(sum(float(g.valor_cop or 0) for g in garantias), 2),
        "saldo_vivo_total_cop": round(sum(saldos[g.id] for g in garantias), 2),
        "buckets": buckets,
    }


@router.get("/{garantia_id}")
def get_garantia(garantia_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    g = db.query(Garantia).filter(Garantia.id == garantia_id).first()
    if not g:
        raise HTTPException(404, "Garantía no encontrada")
    out = _garantia_to_out(g, saldos_vivos(db, [g])[g.id])
    out["movimientos"] = [
        {
            "id": m.id,
            "tipo": m.tipo.value,
            "monto_cop": float(m.monto_cop),
            "saldo_posterior_cop": float(m.saldo_posterior_cop) if m.saldo_posterior_cop is not None else None,
            "fecha": m.fecha.isoformat(),
            "concepto": m.concepto,
            "referencia_xm": m.referencia_xm,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in (g.movimientos or [])
    ]
    return out


@router.post("", status_code=201)
def create_garantia(
    data: GarantiaCreate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    if data.proyecto_id:
        if not db.query(Proyecto).filter(Proyecto.id == data.proyecto_id).first():
            raise HTTPException(404, "Proyecto no encontrado")
    if data.contrato_ppa_id:
        if not db.query(PPAContrato).filter(PPAContrato.id == data.contrato_ppa_id).first():
            raise HTTPException(404, "Contrato PPA no encontrado")

    g = Garantia(**data.model_dump())
    db.add(g)
    db.commit()
    db.refresh(g)
    return _garantia_to_out(g, saldos_vivos(db, [g])[g.id])


@router.patch("/{garantia_id}")
def update_garantia(
    garantia_id: int,
    data: GarantiaUpdate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    g = db.query(Garantia).filter(Garantia.id == garantia_id).first()
    if not g:
        raise HTTPException(404, "Garantía no encontrada")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
    db.commit()
    db.refresh(g)
    return _garantia_to_out(g, saldos_vivos(db, [g])[g.id])


@router.delete("/{garantia_id}", status_code=204)
def delete_garantia(
    garantia_id: int,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    g = db.query(Garantia).filter(Garantia.id == garantia_id).first()
    if not g:
        raise HTTPException(404, "Garantía no encontrada")
    db.delete(g)
    db.commit()


@router.get("/{garantia_id}/movimientos")
def list_movimientos(
    garantia_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    g = db.query(Garantia).filter(Garantia.id == garantia_id).first()
    if not g:
        raise HTTPException(404, "Garantía no encontrada")
    movs = (
        db.query(GarantiaMovimiento)
        .filter(GarantiaMovimiento.garantia_id == garantia_id)
        .order_by(GarantiaMovimiento.fecha.desc())
        .all()
    )
    return [
        {
            "id": m.id,
            "garantia_id": m.garantia_id,
            "tipo": m.tipo.value,
            "monto_cop": float(m.monto_cop),
            "saldo_posterior_cop": float(m.saldo_posterior_cop) if m.saldo_posterior_cop is not None else None,
            "fecha": m.fecha.isoformat(),
            "concepto": m.concepto,
            "referencia_xm": m.referencia_xm,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in movs
    ]


@router.post("/{garantia_id}/movimientos", status_code=201)
def create_movimiento(
    garantia_id: int,
    data: MovimientoCreate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    g = db.query(Garantia).filter(Garantia.id == garantia_id).first()
    if not g:
        raise HTTPException(404, "Garantía no encontrada")

    # Compute running balance
    last_mov = (
        db.query(GarantiaMovimiento)
        .filter(GarantiaMovimiento.garantia_id == garantia_id)
        .order_by(GarantiaMovimiento.fecha.desc(), GarantiaMovimiento.id.desc())
        .first()
    )
    prev_saldo = float(last_mov.saldo_posterior_cop) if last_mov and last_mov.saldo_posterior_cop is not None else float(g.valor_cop or 0)

    if data.tipo in ("deposito", "devolucion", "interes", "renovacion"):
        new_saldo = prev_saldo + abs(data.monto_cop)
    else:
        new_saldo = prev_saldo - abs(data.monto_cop)

    mov = GarantiaMovimiento(
        garantia_id=garantia_id,
        tipo=data.tipo,
        monto_cop=data.monto_cop,
        saldo_posterior_cop=round(new_saldo, 2),
        fecha=data.fecha,
        concepto=data.concepto,
        referencia_xm=data.referencia_xm,
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)
    return {
        "id": mov.id,
        "garantia_id": mov.garantia_id,
        "tipo": mov.tipo.value,
        "monto_cop": float(mov.monto_cop),
        "saldo_posterior_cop": float(mov.saldo_posterior_cop) if mov.saldo_posterior_cop is not None else None,
        "fecha": mov.fecha.isoformat(),
        "concepto": mov.concepto,
        "referencia_xm": mov.referencia_xm,
        "created_at": mov.created_at.isoformat() if mov.created_at else None,
    }
