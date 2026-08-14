"""Snapshot semanal de una estimación de garantía (una fila por ventana y corte)."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, func
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
