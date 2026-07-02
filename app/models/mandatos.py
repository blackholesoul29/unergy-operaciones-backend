import enum
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, Text, Date, DateTime, Boolean,
    ForeignKey, Enum as SAEnum, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoMandatoCostoEnum(str, enum.Enum):
    pendiente_envio        = "pendiente_envio"
    enviado_revisoria      = "enviado_revisoria"
    con_correcciones       = "con_correcciones"
    corregido              = "corregido"
    firmado                = "firmado"
    enviado_inversionista  = "enviado_inversionista"
    sin_inversionista      = "sin_inversionista"


class MandatoInversionista(Base):
    """Tabla maestra: inversionista → correos → proyectos."""
    __tablename__ = "mandato_inversionistas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    correos: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
    proyectos: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    mandatos: Mapped[list["Mandato"]] = relationship("Mandato", back_populates="inversionista")


class Mandato(Base):
    """Un registro por CMU por período."""
    __tablename__ = "mandatos"
    __table_args__ = (
        UniqueConstraint("cmu", "periodo", name="uq_mandato_cmu_periodo"),
        Index("ix_mandatos_periodo", "periodo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cmu: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    periodo: Mapped[date] = mapped_column(Date, nullable=False)  # primer día del mes
    proyecto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tercero: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inversionista_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mandato_inversionistas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoMandatoCostoEnum, name="estado_mandato_costo_enum"),
        nullable=False, default="pendiente_envio",
    )
    observacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_envio_revisoria: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_firmado: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_envio_inversionista: Mapped[date | None] = mapped_column(Date, nullable=True)
    pdf_firmado_ruta: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pdf_firmado_nombre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    archivo_zip_nombre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correo_ref_revisoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correo_ref_envio: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    inversionista: Mapped["MandatoInversionista | None"] = relationship("MandatoInversionista", back_populates="mandatos")
