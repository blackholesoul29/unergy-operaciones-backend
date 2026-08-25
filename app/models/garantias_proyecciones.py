"""Snapshot semanal de una estimación de garantía (una fila por ventana y corte)."""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GarantiaSnapshot(Base):
    __tablename__ = "garantia_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha_corte: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(30), nullable=False)  # resto_mes_actual | mes_siguiente
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    neto_mwh: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    precio_bolsa: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    valor_energia: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    valor_plantas_nuevas: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    costo_regulatorio: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    garantia_total: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    plantas_nuevas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    kwh_planta_nueva: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    regulatorio_anio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regulatorio_mes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regulatorio_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GarantiaPagado(Base):
    """Monto de garantía efectivamente precobrado/pagado por período (ingreso manual)."""
    __tablename__ = "garantia_pagado"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("anio", "mes", name="uq_garantia_pagado_periodo"),)


class BalCttosNeto(Base):
    """Neto real de compras en bolsa del BalCttos de XM, por período (MWh). `dia_corte` =
    último día con dato real del archivo (para proyectar el resto a esa tasa diaria)."""
    __tablename__ = "balcttos_neto"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    dia_corte: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    neto_mwh: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("anio", "mes", name="uq_balcttos_neto_periodo"),)
