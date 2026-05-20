"""Notificaciones — global notification system for users."""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

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
