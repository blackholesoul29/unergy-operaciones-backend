"""Modelos para el panel O&M mensual."""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import BigInteger, Date, Integer, Numeric, Boolean, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class IPCTasa(Base):
    """Tasa IPC anual certificada por el DANE."""
    __tablename__ = "om_ipc_tasas"

    id:          Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    año:         Mapped[int]        = mapped_column(Integer, unique=True, nullable=False)
    tasa:        Mapped[float]      = mapped_column(Numeric(8, 6), nullable=False)
    confirmado:  Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    fuente:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OMSeleccion(Base):
    """Selección mensual: qué contratos O&M van al proveedor y si están facturados."""
    __tablename__ = "om_seleccion_mensual"
    __table_args__ = (
        UniqueConstraint("contrato_id", "periodo", name="uq_om_seleccion_contrato_periodo"),
    )

    id:          Mapped[int]  = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int]  = mapped_column(BigInteger, ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False, index=True)
    periodo:     Mapped[str]  = mapped_column(String(7), nullable=False, index=True)
    incluido:    Mapped[bool] = mapped_column(Boolean, default=True,  nullable=False)
    facturado:   Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    valor_manual: Mapped[float | None] = mapped_column(Numeric(14, 0), nullable=True)  # override del valor a facturar; NULL = usar calculado
    motivo_exclusion: Mapped[str | None] = mapped_column(String(500), nullable=True)  # #6: por qué se excluyó del mes (si incluido=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contrato: Mapped["ContratoServicio"] = relationship("ContratoServicio")


class OMFacturaMensual(Base):
    """Factura consolidada que el proveedor sube al cerrar el mes."""
    __tablename__ = "om_factura_mensual"

    id:             Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    periodo:        Mapped[str]        = mapped_column(String(7), unique=True, nullable=False, index=True)
    nombre_archivo: Mapped[str | None] = mapped_column(String(500),  nullable=True)
    enlace_pdf:     Mapped[str | None] = mapped_column(String(2000), nullable=True)   # Drive URL alternativo
    ruta_local:     Mapped[str | None] = mapped_column(String(1000), nullable=True)   # path en el servidor
    subido_en:      Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:     Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OMPaginaSinMatch(Base):
    """Página del consolidado O&M que no se pudo emparejar automáticamente a un
    contrato; queda pendiente de asignación manual desde Proveedor."""
    __tablename__ = "om_pagina_sin_match"
    __table_args__ = (
        UniqueConstraint("periodo", "pagina", name="uq_om_sin_match_periodo_pagina"),
    )

    id:                   Mapped[int]             = mapped_column(BigInteger, primary_key=True)
    periodo:              Mapped[str]             = mapped_column(String(7), nullable=False, index=True)
    pagina:               Mapped[int]             = mapped_column(Integer, nullable=False)
    nombre_extraido:      Mapped[str | None]      = mapped_column(String(300), nullable=True)
    estrategia:           Mapped[str | None]      = mapped_column(String(30), nullable=True)
    razon:                Mapped[str]             = mapped_column(String(200), nullable=False)
    numero_factura:       Mapped[str | None]      = mapped_column(String(30), nullable=True)
    muestra_texto:        Mapped[str | None]      = mapped_column(String(500), nullable=True)
    origen:               Mapped[str]             = mapped_column(String(20), default="upload", nullable=False)  # "upload" | "backfill"
    resuelto:             Mapped[bool]            = mapped_column(Boolean, default=False, nullable=False)
    contrato_id_asignado: Mapped[int | None]      = mapped_column(BigInteger, ForeignKey("contratos_servicio.id"), nullable=True)
    asignado_en:          Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:           Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())


class OMDocumentoProyecto(Base):
    """PDF individual por proyecto extraído del consolidado mensual."""
    __tablename__ = "om_documento_proyecto"
    __table_args__ = (
        UniqueConstraint("contrato_id", "periodo", name="uq_om_doc_contrato_periodo"),
    )

    id:                   Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    contrato_id:          Mapped[int]           = mapped_column(BigInteger, ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False, index=True)
    periodo:              Mapped[str]           = mapped_column(String(7), nullable=False, index=True)
    nombre_archivo:       Mapped[str]           = mapped_column(String(500), nullable=False)
    ruta_local:           Mapped[str]           = mapped_column(String(1000), nullable=False)
    # Metadata extraída de la factura electrónica
    numero_factura:       Mapped[str | None]    = mapped_column(String(30), nullable=True)
    total_sin_impuestos:  Mapped[float | None]  = mapped_column(Numeric(15, 2), nullable=True)
    iva:                  Mapped[float | None]  = mapped_column(Numeric(15, 2), nullable=True)
    total_pagar:          Mapped[float | None]  = mapped_column(Numeric(15, 2), nullable=True)
    fecha_facturacion:    Mapped[date | None]   = mapped_column(Date, nullable=True)
    cufe:                 Mapped[str | None]    = mapped_column(String(200), nullable=True)
    procesado_en:         Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
