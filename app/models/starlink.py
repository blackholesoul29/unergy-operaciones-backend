"""Modelo para facturas procesadas de Starlink."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, Numeric, DateTime, Boolean, ForeignKey
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


class StarlinkMapeoSitio(Base):
    """Mapeo persistido y editable: nombre de sitio del PDF → proyecto (minigranja).
    Reemplaza el hardcode STARLINK_TO_PANEL del frontend. Match 1:1 por nombre
    normalizado (los splits ya los aplica el parser antes de agrupar)."""
    __tablename__ = "starlink_mapeo_sitio"

    id:          Mapped[int] = mapped_column(BigInteger, primary_key=True)
    patron:      Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    activo:      Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              default=True, server_default="true")
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(), onupdate=func.now())


class StarlinkFacturaLinea(Base):
    """Línea de una factura Starlink resuelta a un proyecto (minigranja).
    Proyección normalizada de agrupado_json: una fila por sitio, con proyecto_id
    (NULL = sin asignar) y el valor sin IVA que consume el consolidado."""
    __tablename__ = "starlink_factura_linea"

    id:          Mapped[int] = mapped_column(BigInteger, primary_key=True)
    factura_id:  Mapped[int] = mapped_column(
        BigInteger, ForeignKey("starlink_facturas.id", ondelete="CASCADE"),
        nullable=False, index=True)
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    descripcion: Mapped[str]   = mapped_column(String(255), nullable=False)
    sin_iva:     Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    iva:         Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    monto_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(), onupdate=func.now())
