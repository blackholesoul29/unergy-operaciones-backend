import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, Date, DateTime, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoMantenimientoEnum(str, enum.Enum):
    preventivo = "preventivo"
    correctivo = "correctivo"
    predictivo = "predictivo"


class EstadoMantenimientoEnum(str, enum.Enum):
    programado = "programado"
    en_ejecucion = "en_ejecucion"
    completado = "completado"
    cancelado = "cancelado"


class Mantenimiento(Base):
    __tablename__ = "mantenimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    registrado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoMantenimientoEnum, name="tipo_mantenimiento_enum"), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoMantenimientoEnum, name="estado_mantenimiento_enum"), nullable=False, default="programado")
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="mantenimientos")
    registrado_por: Mapped["Usuario"] = relationship("Usuario", back_populates="mantenimientos")
