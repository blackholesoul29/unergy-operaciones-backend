from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class ContratoFrontera(Base):
    """Asociación contrato de servicio ↔ frontera (muchos-a-muchos).

    El contrato es el vínculo legal; la frontera es el punto físico de medida
    del que sale la energía que se factura. Un contrato puede cubrir varias
    fronteras y una frontera puede estar en varios contratos (ej. operación y
    representación sobre la misma planta).
    """

    __tablename__ = "contrato_frontera"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_servicio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False, index=True
    )
    frontera_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fronteras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("contrato_servicio_id", "frontera_id", name="uq_contrato_frontera"),
    )
