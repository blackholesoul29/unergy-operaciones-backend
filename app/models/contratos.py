from __future__ import annotations
import enum
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (BigInteger, Integer as sa_Integer, String, Numeric, Boolean, Date,
                        DateTime, ForeignKey, Enum as SAEnum, Text, UniqueConstraint, Table,
                        Column, CheckConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ServicioAplicaEnum(str, enum.Enum):
    operacion = "operacion"
    representacion = "representacion"
    cgm = "cgm"
    promotor = "promotor"
    rec = "rec"
    mantenimiento = "mantenimiento"
    arriendo = "arriendo"
    internet = "internet"


class EstadoPagoEnum(str, enum.Enum):
    pendiente = "pendiente"
    revisado = "revisado"
    aprobado = "aprobado"


class EstadoContratoEnum(str, enum.Enum):
    vigente = "vigente"
    vencido = "vencido"
    terminado = "terminado"
    en_renovacion = "en_renovacion"


class PeriodicidadEnum(str, enum.Enum):
    mensual = "mensual"
    bimestral = "bimestral"
    trimestral = "trimestral"
    anual = "anual"


# Tabla de asociación PPA ↔ Proyectos (muchos-a-muchos)
ppa_contrato_proyectos_table = Table(
    "ppa_contrato_proyectos",
    Base.metadata,
    Column("contrato_id", BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), primary_key=True),
    Column("proyecto_id", BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), primary_key=True),
)


class ContratoServicio(Base):
    __tablename__ = "contratos_servicio"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    numero_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    servicio_aplica: Mapped[str] = mapped_column(SAEnum(ServicioAplicaEnum, name="servicio_aplica_enum"), nullable=False)
    contratante_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contratante_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prestador_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prestador_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contratante_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True, index=True)
    prestador_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True, index=True)
    tiene_cgm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    tiene_promotor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    cgm_codigo_sic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cgm_porcentaje_fncer: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    cgm_tipo_asignacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    promotor_tarifa: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    promotor_condiciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    rec_cantidad: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    rec_precio_unitario: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    rec_vintage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    tarifa_base: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    periodicidad_pago: Mapped[str | None] = mapped_column(SAEnum(PeriodicidadEnum, name="periodicidad_enum"), nullable=True)
    indice_indexacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    canones_otros: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoContratoEnum, name="estado_contrato_enum"), nullable=False, default="vigente")
    fecha_firma_contrato: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicio_om: Mapped[date | None] = mapped_column(Date, nullable=True)  # inicio de operación real (para indexación O&M)
    enlace_drive: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estado_pago: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tarifa_mensual: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    indexacion_anual: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    indexacion_mensual: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    facturas_solenium: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    facturas_inversionistas: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Campos específicos de contratos CGM / Representación
    inversionista_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portafolio: Mapped[str | None] = mapped_column(String(255), nullable=True)
    codigo_sun_factory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nombre_proyecto_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tarifa_admin: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    tarifa_cgm: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    tarifa_representacion: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    indexacion_cgm: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    indexacion_representacion: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Detalles operacionales y contractuales del servicio (texto libre)
    service_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    specific_service_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    slas: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="contratos_servicio")
    contratante: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[contratante_id])
    prestador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[prestador_id])
    pagos: Mapped[list["PagoServicio"]] = relationship("PagoServicio", back_populates="contrato", cascade="all, delete-orphan")


class PPAContrato(Base):
    __tablename__ = "ppa_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    numero_codigo_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nombre_interno: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comprador_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True, index=True)
    vendedor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True, index=True)
    comprador_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comprador_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vendedor_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendedor_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    tarifa_base: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    indice_indexacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    periodicidad_indexacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    periodo_indexacion_base: Mapped[str | None] = mapped_column(String(7), nullable=True)  # YYYY-MM
    valor_indexacion_base: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    cantidad_minima_kwh_mes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    cantidad_maxima_kwh_mes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    periodicidad_facturacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tiempo_pago: Mapped[int | None] = mapped_column(sa_Integer, nullable=True)  # días: 15, 30, 45, 60…
    condiciones_pago: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Datos Gescon (condiciones operativas registradas ante el ASIC)
    gescon_codigo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gescon_fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    gescon_fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    gescon_precio: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    gescon_cantidades_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    codigo_sic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tipo_contrato: Mapped[str | None] = mapped_column(String(20), nullable=True, server_default="venta")
    carpeta_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyectos: Mapped[list["Proyecto"]] = relationship("Proyecto", secondary=ppa_contrato_proyectos_table)
    comprador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[comprador_id])
    vendedor: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[vendedor_id])
    tarifas: Mapped[list["PPATarifa"]] = relationship("PPATarifa", back_populates="contrato", cascade="all, delete-orphan")
    compromisos_energia: Mapped[list["PPACompromisoEnergia"]] = relationship("PPACompromisoEnergia", back_populates="contrato", cascade="all, delete-orphan")


class PPATarifa(Base):
    __tablename__ = "ppa_tarifas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=False, index=True)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    tarifa: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    contrato: Mapped["PPAContrato"] = relationship("PPAContrato", back_populates="tarifas")

    __table_args__ = (
        CheckConstraint("mes >= 1 AND mes <= 12", name="ck_ppa_tarifa_mes_rango"),
        UniqueConstraint("contrato_id", "año", "mes", name="uq_ppa_tarifa_contrato_periodo"),
    )


class PPACompromisoEnergia(Base):
    __tablename__ = "ppa_compromisos_energia"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=False, index=True)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    energia_minima: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    energia_maxima: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    # Plantas inscritas exigidas por el contrato ese mes (condición a cumplir; denominador del
    # indicador de cumplimiento de plantas). Default 0: toda fila arranca en 0 y se completa luego.
    cantidad_proyectos: Mapped[int | None] = mapped_column(sa_Integer, nullable=True, default=0, server_default="0")

    contrato: Mapped["PPAContrato"] = relationship("PPAContrato", back_populates="compromisos_energia")

    __table_args__ = (
        CheckConstraint("mes >= 1 AND mes <= 12", name="ck_ppa_compromiso_mes_rango"),
        UniqueConstraint("contrato_id", "año", "mes", name="uq_ppa_compromiso_contrato_periodo"),
    )


class PagoServicio(Base):
    __tablename__ = "pagos_servicio"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False, index=True)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    valor_pagado: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoPagoEnum, name="estado_pago_enum"), nullable=False, default="pendiente", server_default="pendiente")
    enlace_factura: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contrato: Mapped["ContratoServicio"] = relationship("ContratoServicio", back_populates="pagos")

    __table_args__ = (
        CheckConstraint("mes >= 1 AND mes <= 12", name="ck_pago_servicio_mes_rango"),
        UniqueConstraint("contrato_id", "mes", "año", name="uq_pago_servicio_contrato_periodo"),
    )


