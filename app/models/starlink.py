"""Modelo para facturas procesadas de Starlink."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, Numeric, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class StarlinkFactura(Base):
    """Factura Starlink procesada, almacenada por período (YYYY-MM)."""
    __tablename__ = "starlink_facturas"

    id:             Mapped[int]   = mapped_column(BigInteger, primary_key=True)
    periodo:        Mapped[str]   = mapped_column(String(7),  unique=True, nullable=False, index=True)
    items_json:     Mapped[str]   = mapped_column(Text, nullable=False)   # JSON array ItemDetalle
    agrupado_json:  Mapped[str]   = mapped_column(Text, nullable=False)   # JSON array ItemAgrupado
    cargos_totales: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    suma_items:     Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:     Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                      server_default=func.now(), onupdate=func.now())
