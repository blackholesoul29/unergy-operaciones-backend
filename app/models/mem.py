"""
Modelos del módulo MEM (Mercado de Energía Mayorista).

Ingesta automatizada de datos de XM:
  - `MEMDatosASIC`      → generación horaria reportada por el ASIC.
  - `MEMPrecioBolsa`    → precio horario de bolsa.
  - `MEMGesconEstado`   → estado de los contratos/plantas en GESCON.
  - `LiquidacionPreliminar` → resultado de la pre-liquidación automática que
    alimenta el módulo de liquidaciones.

Convenciones del repo: PK BIGSERIAL (BigInteger), timestamps timezone-aware con
`server_default=func.now()`, enums Postgres nombrados explícitamente.
"""
import enum
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, Integer, Float, String, Date, DateTime, Boolean,
    ForeignKey, Enum as SAEnum, Text, UniqueConstraint, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoLiquidacionPreliminarEnum(str, enum.Enum):
    pendiente_revision = "pendiente_revision"
    aprobada = "aprobada"
    rechazada = "rechazada"


class MEMDatosASIC(Base):
    """Generación horaria por proyecto reportada por el ASIC de XM."""
    __tablename__ = "mem_datos_asic"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "fecha", "hora", name="uq_mem_asic_proyecto_fecha_hora"),
        CheckConstraint("hora >= 0 AND hora <= 23", name="ck_mem_asic_hora"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    generacion_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    fuente: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")


class MEMPrecioBolsa(Base):
    """Precio horario de bolsa del MEM (COP/kWh)."""
    __tablename__ = "mem_precios_bolsa"
    __table_args__ = (
        UniqueConstraint("fecha", "hora", name="uq_mem_precio_fecha_hora"),
        CheckConstraint("hora >= 0 AND hora <= 23", name="ck_mem_precio_hora"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hora: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_cop_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MEMGesconEstado(Base):
    """Estado de un proyecto/contrato en GESCON."""
    __tablename__ = "mem_gescon_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    estado: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")


class LiquidacionPreliminar(Base):
    """Resultado de la pre-liquidación automática a partir de los datos del MEM."""
    __tablename__ = "liquidaciones_preliminares"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", name="uq_liq_preliminar_proyecto_periodo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    liquidacion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("liquidaciones.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    periodo: Mapped[date] = mapped_column(Date, nullable=False)  # primer día del mes
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoLiquidacionPreliminarEnum, name="estado_liquidacion_preliminar_enum"),
        nullable=False, default="pendiente_revision",
    )
    datos_calculados = mapped_column(JSONB, nullable=True)
    invoice_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
    liquidacion: Mapped["Liquidacion | None"] = relationship("Liquidacion")
