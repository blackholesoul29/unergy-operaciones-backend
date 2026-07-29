from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (BigInteger, String, Numeric, Date, DateTime,
                        ForeignKey, Text, UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class GeneracionDiaria(Base):
    __tablename__ = "generacion_diaria"
    __table_args__ = (
        Index("ix_generacion_diaria_fecha", "fecha"),
        UniqueConstraint("proyecto_id", "fecha", name="uq_generacion_proyecto_fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    kwh_real: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    kwh_p90: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    kwh_autoconsumo: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    fuente: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="generaciones")
