from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Numeric, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VerificacionCosto(Base):
    """Verificación manual de costos por proyecto: costos del generador vs del
    comercializador y AC Power. Un registro por proyecto (editable a mano;
    a futuro se pre-llenará desde la API fuente)."""

    __tablename__ = "verificacion_costos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), unique=True, index=True, nullable=False
    )
    costos_generador: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    costos_comercializador: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ac_power: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
