import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Boolean, Date, DateTime,
                        Integer, ForeignKey, Enum as SAEnum, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoSeguimientoEnum(str, enum.Enum):
    pendiente = "pendiente"
    en_revision = "en_revision"
    cumplido = "cumplido"


class EstadoInstanciaEnum(str, enum.Enum):
    activo = "activo"
    inactivo = "inactivo"


class PromoterCatalogoRequisito(Base):
    __tablename__ = "promotor_catalogo_requisitos"

    id: Mapped[str] = mapped_column(String(10), primary_key=True)  # '9.1', ..., 'FDOC'
    nombre: Mapped[str] = mapped_column(String(500), nullable=False)
    plazo_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL para FDOC
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    seguimientos: Mapped[list["PromoterSeguimiento"]] = relationship("PromoterSeguimiento", back_populates="requisito")


class PromoterSeguimiento(Base):
    __tablename__ = "promotor_seguimientos"
    __table_args__ = (UniqueConstraint("proyecto_id", "requisito_id", name="uq_promotor_proyecto_requisito"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    requisito_id: Mapped[str] = mapped_column(String(10), ForeignKey("promotor_catalogo_requisitos.id"), nullable=False)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoSeguimientoEnum, name="estado_seguimiento_enum"), nullable=False, default="pendiente")
    estado_instancia: Mapped[str] = mapped_column(SAEnum(EstadoInstanciaEnum, name="estado_instancia_enum"), nullable=False, default="activo")
    fecha_primer_documento: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_limite_calculada: Mapped[date | None] = mapped_column(Date, nullable=True)
    descripcion_observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsable: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_ultima_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="promotor_seguimientos")
    requisito: Mapped["PromoterCatalogoRequisito"] = relationship("PromoterCatalogoRequisito", back_populates="seguimientos")
