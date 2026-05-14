from __future__ import annotations
import enum
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (BigInteger, Integer as sa_Integer, String, Numeric, Boolean, Date,
                        DateTime, ForeignKey, Enum as SAEnum, Text, UniqueConstraint, Table, Column)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ServicioAplicaEnum(str, enum.Enum):
    operacion = "operacion"
    representacion = "representacion"
    cgm = "cgm"
    promotor = "promotor"
    rec = "rec"


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
    proyecto_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True)
    numero_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    servicio_aplica: Mapped[str] = mapped_column(SAEnum(ServicioAplicaEnum, name="servicio_aplica_enum"), nullable=False)
    contratante_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contratante_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prestador_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prestador_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contratante_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True)
    prestador_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="contratos_servicio")
    documentos: Mapped[list] = relationship("Documento", primaryjoin="and_(Documento.entity_type=='contrato_servicio', foreign(Documento.entity_id)==ContratoServicio.id)", viewonly=True)
    contratante: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[contratante_id])
    prestador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[prestador_id])


class PPAContrato(Base):
    __tablename__ = "ppa_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    numero_codigo_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nombre_interno: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comprador_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True)
    vendedor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyectos: Mapped[list["Proyecto"]] = relationship("Proyecto", secondary=ppa_contrato_proyectos_table)
    comprador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[comprador_id])
    vendedor: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[vendedor_id])
    tarifas: Mapped[list["PPATarifa"]] = relationship("PPATarifa", back_populates="contrato", cascade="all, delete-orphan")
    compromisos_energia: Mapped[list["PPACompromisoEnergia"]] = relationship("PPACompromisoEnergia", back_populates="contrato", cascade="all, delete-orphan")


class PPATarifa(Base):
    __tablename__ = "ppa_tarifas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=False)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    tarifa: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    contrato: Mapped["PPAContrato"] = relationship("PPAContrato", back_populates="tarifas")

    __table_args__ = (UniqueConstraint("contrato_id", "año", "mes", name="uq_ppa_tarifa_contrato_periodo"),)


class PPACompromisoEnergia(Base):
    __tablename__ = "ppa_compromisos_energia"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=False)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    energia_minima: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    energia_maxima: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    cantidad_proyectos: Mapped[int | None] = mapped_column(sa_Integer, nullable=True)

    contrato: Mapped["PPAContrato"] = relationship("PPAContrato", back_populates="compromisos_energia")

    __table_args__ = (UniqueConstraint("contrato_id", "año", "mes", name="uq_ppa_compromiso_contrato_periodo"),)


class ContratoArriendo(Base):
    __tablename__ = "contratos_arriendo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    propietario_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    hectareas: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    verificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="contratos_arriendo")
