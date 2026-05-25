"""Garantías XM — guarantee/warranty tracking for solar projects."""
import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base, TimestampMixin


class TipoGarantiaEnum(str, enum.Enum):
    cuenta_custodia = "cuenta_custodia"
    poliza = "poliza"
    carta_credito = "carta_credito"
    fiducia = "fiducia"
    otro = "otro"


class EstadoGarantiaEnum(str, enum.Enum):
    vigente = "vigente"
    vencida = "vencida"
    en_renovacion = "en_renovacion"
    liberada = "liberada"
    en_proceso = "en_proceso"


class TipoMovimientoEnum(str, enum.Enum):
    deposito = "deposito"
    cobro_xm = "cobro_xm"
    devolucion = "devolucion"
    ajuste = "ajuste"
    interes = "interes"
    renovacion = "renovacion"


class Garantia(TimestampMixin, Base):
    __tablename__ = "garantias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proyecto_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    contrato_ppa_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id"), nullable=True, index=True)
    codigo_frontera: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    tipo: Mapped[TipoGarantiaEnum] = mapped_column(Enum(TipoGarantiaEnum), nullable=False)
    entidad: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    numero_referencia: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    valor_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    porcentaje_cobertura: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)

    fecha_constitucion: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fecha_vencimiento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estado: Mapped[EstadoGarantiaEnum] = mapped_column(
        Enum(EstadoGarantiaEnum), nullable=False, default=EstadoGarantiaEnum.vigente
    )
    observaciones: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    proyecto = relationship("Proyecto", backref="garantias", lazy="select")
    contrato_ppa = relationship("PPAContrato", backref="garantias", lazy="select")
    movimientos = relationship("GarantiaMovimiento", back_populates="garantia", cascade="all, delete-orphan", order_by="GarantiaMovimiento.fecha.desc()")


class GarantiaMovimiento(Base):
    __tablename__ = "garantias_movimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    garantia_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("garantias.id", ondelete="CASCADE"), nullable=False, index=True)

    tipo: Mapped[TipoMovimientoEnum] = mapped_column(Enum(TipoMovimientoEnum), nullable=False)
    monto_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    saldo_posterior_cop: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    concepto: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referencia_xm: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    garantia = relationship("Garantia", back_populates="movimientos")
