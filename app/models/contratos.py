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
    semestral = "semestral"
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
    # NULL = sin dato (la UI muestra "—"); False = explícitamente no renueva
    renovacion_automatica: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fecha_indexacion: Mapped[date | None] = mapped_column(Date, nullable=True)  # fecha de indexación de tarifas
    responsable_iva: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enlace_drive: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estado_pago: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Campos informativos del plan de Internet (solo aplican a servicio_aplica='internet')
    plan_datos_gb: Mapped[str | None] = mapped_column(String(50), nullable=True)
    velocidad_mbps: Mapped[int | None] = mapped_column(sa_Integer, nullable=True)
    tipo_conexion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linea_servicio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    id_router: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_kit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latencia_ms: Mapped[int | None] = mapped_column(sa_Integer, nullable=True)
    wifi_seguridad: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wifi_password: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ubicacion_lat: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    ubicacion_lng: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="contratos_servicio")
    contratante: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[contratante_id])
    prestador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[prestador_id])
    pagos: Mapped[list["PagoServicio"]] = relationship("PagoServicio", back_populates="contrato", cascade="all, delete-orphan")


class PPAResponsable(Base):
    """Empresa responsable de un PPA (normalmente Unergy; en algunos contratos es
    un tercero). Es un catálogo —y no un texto libre en el contrato— para que los
    filtros de la plataforma trabajen sobre valores consistentes.

    `incluir_en_cumplimiento` marca si los contratos de este responsable son
    relevantes para nosotros: los que están en False desaparecen de la Matriz
    anual de /mem/cumplimiento (ver `_query_contratos_venta(solo_relevantes=True)`).
    Un contrato SIN responsable (responsable_id NULL) siempre se incluye: nada se
    esconde por omisión, solo por marca explícita."""
    __tablename__ = "ppa_responsables"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    incluir_en_cumplimiento: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contratos: Mapped[list["PPAContrato"]] = relationship("PPAContrato", back_populates="responsable")


class PPAContrato(Base):
    __tablename__ = "ppa_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    numero_codigo_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nombre_interno: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responsable_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ppa_responsables.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    # NULL = sin dato (la UI muestra "—"); False = explícitamente no renueva
    renovacion_automatica: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyectos: Mapped[list["Proyecto"]] = relationship("Proyecto", secondary=ppa_contrato_proyectos_table)
    responsable: Mapped[Optional["PPAResponsable"]] = relationship("PPAResponsable", back_populates="contratos")
    comprador: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[comprador_id])
    vendedor: Mapped[Optional["Cliente"]] = relationship("Cliente", foreign_keys=[vendedor_id])
    tarifas: Mapped[list["PPATarifa"]] = relationship("PPATarifa", back_populates="contrato", cascade="all, delete-orphan")
    compromisos_energia: Mapped[list["PPACompromisoEnergia"]] = relationship("PPACompromisoEnergia", back_populates="contrato", cascade="all, delete-orphan")


class IppMensual(Base):
    """Índice IPP publicado (global) por mes. Numerador de la indexación de PPAs:
    tarifa_indexada = tarifa_base × (IPP_del_mes / valor_indexacion_base_del_PPA).
    Es un solo valor por período (mismo para todos los contratos), a diferencia del
    IPP base que es por PPA. Fuente: DANE (IPP)."""
    __tablename__ = "ipp_mensual"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("mes >= 1 AND mes <= 12", name="ck_ipp_mensual_mes_rango"),
        UniqueConstraint("año", "mes", name="uq_ipp_mensual_periodo"),
    )


class FacturaAgrupacion(Base):
    """Agrupación manual de CONTRATOS (código SIC) en una factura con nombre (ej.
    dividir 'Terpel 2' en 'Terpel 2 PA' y 'Terpel 2 Sol de la Sierra'). Se llavea por
    CONTRATO —no por proyecto— porque un proyecto puede tener varios contratos con
    tarifas distintas (transición de comercializador). Fija: se define una vez y
    aplica cada mes. Contrato sin asignación agrupa por su PPA (default). La tarifa
    NO cambia (sale del PPA); esto solo reagrupa para la emisión de facturas."""
    __tablename__ = "factura_agrupacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_sic_contrato: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # % del contrato que va a esta factura; el resto (100-%) queda en el PPA default.
    # NULL = 100% (el contrato entero se mueve). Ej. Uruaco 78596: 22.8066% → "Terpel 1
    # Suno", 77.1934% queda en Terpel 1. Misma tarifa (solo reparte kWh/valor).
    porcentaje: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FacturaOrden(Base):
    """Orden manual de las facturas en la vista de emisión. Se llavea por NOMBRE de
    factura (no hay id: la factura es el resultado de agrupar contratos), y es fijo:
    se define una vez y aplica cada mes, como la agrupación. Una factura sin fila
    aquí va al final, ordenada por valor como antes."""
    __tablename__ = "factura_orden"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    orden: Mapped[int] = mapped_column(sa_Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FacturaEmitida(Base):
    """Marca de "ya se facturó", por factura y PERÍODO (a diferencia del orden y la
    agrupación, que son fijos). La presencia de la fila es la marca; se borra al
    desmarcar. Guarda quién y cuándo para tener rastro."""
    __tablename__ = "factura_emitida"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    numero_factura: Mapped[str | None] = mapped_column(String(80), nullable=True)  # código de la factura emitida
    emitida_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emitida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("nombre", "periodo", name="uq_factura_emitida_nombre_periodo"),
    )


class DespachoContratoDia(Base):
    """Energía diaria por contrato XM (suma de las 24 horas de ese día), ingerida
    del despacho. Permite ver/filtrar el día a día de un contrato. Se llena al subir
    el despacho, junto con el agregado mensual."""
    __tablename__ = "despacho_contrato_dia"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    periodo: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # "YYYY-MM"
    codigo_sic_contrato: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    kwh: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("periodo", "codigo_sic_contrato", "fecha", name="uq_despacho_dia"),
    )


class PrecioBolsaMensual(Base):
    """Precio de bolsa ($/kWh) manual por mes para valorizar la energía de los
    contratos SIN PPA (UNGC / bolsa), que XM factura a precio de bolsa. Si no se
    fija, se usa el promedio de precios_bolsa_diario como sugerido."""
    __tablename__ = "precio_bolsa_mensual"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    año: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    mes: Mapped[int] = mapped_column(sa_Integer, nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("año", "mes", name="uq_precio_bolsa_periodo"),
    )


class DespachoContratoMensual(Base):
    """Energía mensual por contrato XM, ingerida del archivo de despachos de XM
    (dspcttos_txf_MM.xlsx). Un registro por (período, contrato). kwh = suma de las
    24 horas de todos los días del mes para ese contrato. Es el insumo de energía
    de la facturación v2 (el único dato externo)."""
    __tablename__ = "despacho_contrato_mensual"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    codigo_sic_contrato: Mapped[str] = mapped_column(String(40), nullable=False)
    vendedor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comprador: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kwh: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Días efectivamente incluidos en el despacho (para facturas de mes parcial): se
    # derivan de las fechas del archivo (FechaDocumento), no se hardcodean.
    dias: Mapped[int | None] = mapped_column(sa_Integer, nullable=True)
    fecha_min: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_max: Mapped[date | None] = mapped_column(Date, nullable=True)
    archivo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("periodo", "codigo_sic_contrato", name="uq_despacho_periodo_contrato"),
    )


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


