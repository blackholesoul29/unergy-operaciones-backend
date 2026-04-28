from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Boolean, Date, DateTime,
                        Numeric, ForeignKey, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class GeneracionDiaria(Base):
    __tablename__ = "generacion_diaria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    kwh_real: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    kwh_p90: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    kwh_autoconsumo: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    fuente: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")  # type: ignore[name-defined]


class MonitoreoVerificacion(Base):
    __tablename__ = "monitoreo_verificaciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    codigo: Mapped[str] = mapped_column(String(6), nullable=False)
    usado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
