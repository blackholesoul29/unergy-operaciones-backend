"""Notificaciones — global notification system for users."""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import _require_admin, get_current_user
from app.core.database import get_db
from app.models.notificaciones import Notificacion, NotificacionAlerta, TipoNotificacionEnum
from app.models.usuarios import Usuario
from app.schemas.notificaciones import (
    NotificacionAlertaCreate,
    NotificacionAlertaMarkRead,
    NotificacionAlertaResponse,
    NotificacionOut,
)
from app.services.email_service import send_alerta_email

logger = logging.getLogger("notificaciones")

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


def crear_notificacion(
    db: Session,
    usuario_id: int,
    tipo: str,
    titulo: str,
    mensaje: str,
    link: str | None = None,
) -> Notificacion:
    """Helper function for use by other modules to create notifications."""
    n = Notificacion(
        usuario_id=usuario_id,
        tipo=TipoNotificacionEnum(tipo),
        titulo=titulo,
        mensaje=mensaje,
        link=link,
    )
    db.add(n)
    db.flush()
    return n


def create_notificacion_alerta(
    db: Session,
    usuario_id: int,
    titulo: str,
    mensaje: str,
    severidad: str = "critica",
    canal: str = "in_app",
    alerta_ref: str | None = None,
    email_to: str | None = None,
) -> NotificacionAlerta:
    """Crea (y opcionalmente despacha por email) una notificación de alerta.

    Núcleo reutilizable usado tanto por el endpoint `/trigger` como por el hook
    de alertas. El envío de email es no-fatal: si falla, la notificación se
    persiste igualmente con `email_enviado=False`.
    """
    n = NotificacionAlerta(
        usuario_id=usuario_id,
        titulo=titulo,
        mensaje=mensaje,
        severidad=severidad,
        canal=canal,
        alerta_ref=alerta_ref,
    )

    if canal in ("email", "ambos") and email_to:
        try:
            n.email_enviado = send_alerta_email(
                to_email=email_to,
                titulo=titulo,
                mensaje=mensaje,
                severidad=severidad,
            )
        except Exception as exc:  # pragma: no cover — defensivo
            logger.error("Fallo enviando email de alerta a %s: %s", email_to, exc)
            n.email_enviado = False

    db.add(n)
    db.commit()
    db.refresh(n)
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


# ── Notificaciones de alertas (contratos PPA) ────────────────────────────────

@router.get("/me", response_model=list[NotificacionAlertaResponse])
def list_alertas_me(
    solo_no_leidas: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Notificaciones de alerta del usuario actual, más recientes primero."""
    q = db.query(NotificacionAlerta).filter(NotificacionAlerta.usuario_id == current.id)
    if solo_no_leidas:
        q = q.filter(NotificacionAlerta.leida == False)
    return (
        q.order_by(NotificacionAlerta.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/me/count")
def count_alertas_me(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Conteo de notificaciones de alerta no leídas (para el badge)."""
    count = (
        db.query(func.count(NotificacionAlerta.id))
        .filter(
            NotificacionAlerta.usuario_id == current.id,
            NotificacionAlerta.leida == False,
        )
        .scalar()
    ) or 0
    return {"no_leidas": count}


@router.post("/mark-read")
def mark_alertas_read(
    body: NotificacionAlertaMarkRead,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Marca como leídas las notificaciones de alerta indicadas del usuario actual."""
    if not body.ids:
        return {"actualizadas": 0}
    updated = (
        db.query(NotificacionAlerta)
        .filter(
            NotificacionAlerta.id.in_(body.ids),
            NotificacionAlerta.usuario_id == current.id,
            NotificacionAlerta.leida == False,
        )
        .update(
            {"leida": True, "leida_at": datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    )
    db.commit()
    return {"actualizadas": updated}


@router.post("/trigger", response_model=NotificacionAlertaResponse)
def trigger_alerta(
    body: NotificacionAlertaCreate,
    db: Session = Depends(get_db),
    _admin: Usuario = Depends(_require_admin),
):
    """Crea y despacha una notificación de alerta (admin/testing)."""
    email_to = None
    if body.canal in ("email", "ambos"):
        destinatario = db.query(Usuario).filter(Usuario.id == body.usuario_id).first()
        email_to = destinatario.email if destinatario else None

    return create_notificacion_alerta(
        db,
        usuario_id=body.usuario_id,
        titulo=body.titulo,
        mensaje=body.mensaje,
        severidad=body.severidad,
        canal=body.canal,
        alerta_ref=body.alerta_ref,
        email_to=email_to,
    )
