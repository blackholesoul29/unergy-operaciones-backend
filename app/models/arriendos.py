"""Modelos para el panel de Arriendos mensual (mirror de O&M)."""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import BigInteger, Integer, Numeric, Boolean, String, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class ArrProyecto(Base):
    __tablename__ = "arr_proyectos"

    id:          Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    codigo:      Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    nombre:      Mapped[str]        = mapped_column(String(255), nullable=False)
    fecha_firma_contrato: Mapped[date | None] = mapped_column(Date, nullable=True)
    valor_base:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    canon_archivo: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    activo:      Mapped[bool]       = mapped_column(Boolean, default=True, nullable=False)
    created_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArrIPCTasa(Base):
    __tablename__ = "arr_ipc_tasas"

    id:          Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    año:         Mapped[int]        = mapped_column(Integer, unique=True, nullable=False)
    tasa:        Mapped[float]      = mapped_column(Numeric(8, 6), nullable=False)
    confirmado:  Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    fuente:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArrDocumento(Base):
    """Documento de pago de arriendo (cuenta_cobro, factura) por proyecto, período y pago_id."""
    __tablename__ = "arr_documento"
    __table_args__ = (
        UniqueConstraint("arr_proyecto_id", "periodo", "pago_id", name="uq_arr_doc_proyecto_periodo_pago"),
    )

    id:                Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    arr_proyecto_id:   Mapped[int]        = mapped_column(BigInteger, ForeignKey("arr_proyectos.id", ondelete="CASCADE"), nullable=False, index=True)
    periodo:           Mapped[str]        = mapped_column(String(7), nullable=False, index=True)
    pago_id:           Mapped[int]        = mapped_column(Integer, nullable=False)
    codigo_contrato:   Mapped[str]        = mapped_column(String(120), nullable=False)
    tipo_documento:    Mapped[str]        = mapped_column(String(30), nullable=False)   # cuenta_cobro | factura_electronica
    nombre_archivo:    Mapped[str]        = mapped_column(String(500), nullable=False)
    ruta_local:        Mapped[str]        = mapped_column(String(1000), nullable=False)
    nombre_secundario: Mapped[str | None] = mapped_column(String(500), nullable=True)   # enviada PDF
    ruta_secundario:   Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Datos extraídos de la cuenta de cobro (matching por predio)
    codigo_predio:        Mapped[str | None]   = mapped_column(String(120), nullable=True)   # ej. COLCEST45P8
    numero_cuenta_cobro:  Mapped[str | None]   = mapped_column(String(60),  nullable=True)   # ej. UNERGY-309-84
    nombre_arrendatario:  Mapped[str | None]   = mapped_column(String(255), nullable=True)
    valor_individual:     Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    fecha_subida:      Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArrSeleccion(Base):
    __tablename__ = "arr_seleccion_mensual"
    __table_args__ = (
        UniqueConstraint("arr_proyecto_id", "periodo", name="uq_arr_seleccion_proyecto_periodo"),
    )

    id:              Mapped[int]  = mapped_column(BigInteger, primary_key=True)
    arr_proyecto_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("arr_proyectos.id", ondelete="CASCADE"), nullable=False, index=True)
    periodo:         Mapped[str]  = mapped_column(String(7), nullable=False, index=True)
    incluido:        Mapped[bool] = mapped_column(Boolean, default=True,  nullable=False)
    facturado:       Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
