"""Monitoreo de cobertura de garantías — histórico de verificaciones.

Cada corrida del job `verificar_cobertura_de_garantias` deja una fila aquí con
el resultado del cálculo de exposición vs. valor de la garantía. Las columnas de
configuración (umbrales, tipo de cálculo, activación) viven en `garantias`.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class GarantiaCoberturaHistorico(Base):
    __tablename__ = "garantia_cobertura_historico"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    garantia_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("garantias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha_verificacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    valor_requerido: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    valor_actual_garantia: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    cobertura_porcentaje: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    nivel_alerta: Mapped[str] = mapped_column(String(20), nullable=False)  # VERDE, AMARILLO, ROJO
    detalles_calculo: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    garantia = relationship("Garantia", back_populates="cobertura_historico")
