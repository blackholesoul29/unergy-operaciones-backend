"""Notificaciones — global notification system for users."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.notificaciones import Notificacion, TipoNotificacionEnum
from app.models.usuarios import Usuario
from app.schemas.notificaciones import NotificacionOut

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


def crear_notificacion(
    db: Session,
    usuario_id: int,
    tipo: str,
    titulo: str,
    mensaje: str,
) -> Notificacion:
    """Helper function for use by other modules to create notifications."""
    n = Notificacion(
        usuario_id=usuario_id,
        tipo=TipoNotificacionEnum(tipo),
        titulo=titulo,
        mensaje=mensaje,
    )
    db.add(n)
    db.flush()
    return n


@router.get("", response_model=list[NotificacionOut])
def list_notificaciones(
    leida: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """List notifications for the current user (paginated, optionally filtered by read status)."""
    q = db.query(Notificacion).filter(Notificacion.usuario_id == current.id)
    if leida is not None:
        q = q.filter(Notificacion.leida == leida)
    items = (
        q.order_by(Notificacion.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return items


@router.get("/count")
def count_unread(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Return the count of unread notifications for the current user."""
    count = (
        db.query(func.count(Notificacion.id))
        .filter(Notificacion.usuario_id == current.id, Notificacion.leida == False)
        .scalar()
    ) or 0
    return {"no_leidas": count}


@router.patch("/{id}/leer", response_model=NotificacionOut)
def mark_as_read(
    id: int,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Mark a single notification as read."""
    n = db.query(Notificacion).filter(
        Notificacion.id == id,
        Notificacion.usuario_id == current.id,
    ).first()
    if not n:
        raise HTTPException(404, "Notificacion no encontrada")
    n.leida = True
    db.commit()
    db.refresh(n)
    return n


@router.patch("/leer-todas")
def mark_all_as_read(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    updated = (
        db.query(Notificacion)
        .filter(Notificacion.usuario_id == current.id, Notificacion.leida == False)
        .update({"leida": True}, synchronize_session=False)
    )
    db.commit()
    return {"actualizadas": updated}
