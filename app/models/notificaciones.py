"""Notificaciones — global notification system for users."""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import false

from app.models.base import Base


class TipoNotificacionEnum(str, enum.Enum):
    alerta = "alerta"
    info = "info"
    accion = "accion"


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tipo: Mapped[TipoNotificacionEnum] = mapped_column(
        SAEnum(TipoNotificacionEnum, name="tipo_notificacion_enum"),
        nullable=False,
    )
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    leida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    link: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    usuario = relationship("Usuario", backref="notificaciones", lazy="select")


class NotificacionAlerta(Base):
    """Notificaciones proactivas de alertas de contratos PPA.

    Tabla independiente de `notificaciones` para rastrear envíos y estado de
    lectura de alertas (severidad, canal, despacho de email).
    """
    __tablename__ = "notificaciones_alertas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Referencia lógica a la alerta origen (p.ej. cumplimiento_ppa:<contrato>:<periodo>).
    alerta_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    # critica | persistente | info
    severidad: Mapped[str] = mapped_column(String(20), nullable=False, default="critica")
    # in_app | email | ambos
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="in_app")
    leida: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False,
    )
    email_enviado: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    leida_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
