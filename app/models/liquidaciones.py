import enum
from datetime import datetime, date
from typing import List
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text, UniqueConstraint, CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoLiquidacionEnum(str, enum.Enum):
    iniciada = "iniciada"
    costos_registrados = "costos_registrados"
    xm_procesado = "xm_procesado"
    mandatos_emitidos = "mandatos_emitidos"
    en_contabilidad = "en_contabilidad"
    en_revisoria = "en_revisoria"
    facturado = "facturado"
    entregado = "entregado"


class TipoVentaLiqEnum(str, enum.Enum):
    bolsa = "bolsa"
    ppa = "ppa"
    interno = "interno"
    autoconsumo = "autoconsumo"


class TipoCostoEnum(str, enum.Enum):
    mantenimiento = "mantenimiento"
    internet = "internet"
    arriendo = "arriendo"
    polizas = "polizas"
    comercializacion_xm = "comercializacion_xm"
    servicios_publicos = "servicios_publicos"
    cambio_equipos_medida = "cambio_equipos_medida"
    otro = "otro"


class TipoMandatoEnum(str, enum.Enum):
    ingresos = "ingresos"
    costos = "costos"


class EstadoMandatoEnum(str, enum.Enum):
    borrador = "borrador"
    enviado_revisoria = "enviado_revisoria"
    firmado = "firmado"
    entregado = "entregado"


class TipoLineaMandatoEnum(str, enum.Enum):
    # Ingresos — estructura simple (PPA / bolsa directa)
    ingreso_bruto = "ingreso_bruto"
    ajuste_xm = "ajuste_xm"
    ajuste_unergy = "ajuste_unergy"
    ajuste_comercializacion = "ajuste_comercializacion"
    intereses = "intereses"
    otro_ingreso = "otro_ingreso"
    # Ingresos — estructura mercado (despacho XM)
    despacho = "despacho"
    ventas_en_bolsa = "ventas_en_bolsa"
    compras_en_bolsa = "compras_en_bolsa"
    redistribucion_ingresos = "redistribucion_ingresos"
    # Costos operativos
    mantenimiento = "mantenimiento"
    arriendo = "arriendo"
    servicio_internet = "servicio_internet"
    poliza_cumplimiento = "poliza_cumplimiento"
    servicios_publicos_consumo = "servicios_publicos_consumo"
    cambio_equipos_medida = "cambio_equipos_medida"
    seguro = "seguro"
    otro_costo = "otro_costo"
    # Factura servicios
    comercializacion = "comercializacion"
    representacion = "representacion"
    cgm = "cgm"
    administracion = "administracion"
    # Impuestos / retenciones
    iva = "iva"
    retencion_fuente = "retencion_fuente"
    reteica = "reteica"
    ica_opex = "ica_opex"
    otro_impuesto = "otro_impuesto"
    # Totales
    porcentaje_participacion = "porcentaje_participacion"
    valor_a_pagar = "valor_a_pagar"


class TipoFacturaServicioEnum(str, enum.Enum):
    representacion = "representacion"
    cgm = "cgm"
    administracion_operacion = "administracion_operacion"


class EstadoFacturaEnum(str, enum.Enum):
    emitida = "emitida"
    pagada = "pagada"
    vencida = "vencida"


class Liquidacion(Base):
    __tablename__ = "liquidaciones"
    __table_args__ = (UniqueConstraint("proyecto_id", "periodo", name="uq_liquidacion_proyecto_periodo"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    generado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    periodo: Mapped[date] = mapped_column(Date, nullable=False)  # primer día del mes
    tipo_venta: Mapped[str] = mapped_column(SAEnum(TipoVentaLiqEnum, name="tipo_venta_liq_enum"), nullable=False)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoLiquidacionEnum, name="estado_liquidacion_enum"), nullable=False, default="iniciada")
    fecha_inicio_proceso: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    consecutivo_inicial_ingresos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutivo_inicial_costos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comprobante_contable_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estado_resultados_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Estado de resultados embebido
    ingresos_energia_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    costos_comercializacion_xm_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    costos_operativos_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ingreso_neto_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    ingreso_neto_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    tasa_cambio: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    observaciones_resultados: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Informe PDF editable (HTML embebido, misma dinámica que informes de monitoreo)
    informe_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    informe_actualizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="liquidaciones")
    generado_por: Mapped["Usuario"] = relationship("Usuario", back_populates="liquidaciones")
    costos: Mapped[List["LiquidacionCosto"]] = relationship("LiquidacionCosto", back_populates="liquidacion")
    xm_datos: Mapped[List["LiquidacionXMDato"]] = relationship("LiquidacionXMDato", back_populates="liquidacion")
    mandatos: Mapped[List["LiquidacionMandato"]] = relationship("LiquidacionMandato", back_populates="liquidacion")
    facturas: Mapped[List["LiquidacionFactura"]] = relationship("LiquidacionFactura", back_populates="liquidacion")


class LiquidacionCosto(Base):
    __tablename__ = "liquidacion_costos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    liquidacion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("liquidaciones.id"), nullable=False, index=True)
    tipo_costo: Mapped[str] = mapped_column(SAEnum(TipoCostoEnum, name="tipo_costo_enum"), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(500), nullable=False)
    proveedor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nro_soporte: Mapped[str | None] = mapped_column(String(100), nullable=True)
    soporte_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    valor_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    liquidacion: Mapped["Liquidacion"] = relationship("Liquidacion", back_populates="costos")


class LiquidacionXMDato(Base):
    __tablename__ = "liquidacion_xm_datos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    liquidacion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("liquidaciones.id"), nullable=False, index=True)
    # RESTRICT explicito (migracion 083, antes era el NO ACTION implicito de
    # Postgres -- mismo efecto practico, pero sin depender de un default sin
    # documentar) -- dato financiero de liquidacion, igual criterio que
    # reporte_energia_generacion/consumo/exclusion.
    frontera_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fronteras.id", ondelete="RESTRICT"), nullable=True, index=True)
    tipo_venta: Mapped[str] = mapped_column(SAEnum(TipoVentaLiqEnum, name="tipo_venta_xm_enum", create_constraint=False), nullable=False)
    energia_kwh: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    tarifa_aplicada_kwh: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    valor_bruto_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    referencia_factura_xm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_factura_xm: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    liquidacion: Mapped["Liquidacion"] = relationship("Liquidacion", back_populates="xm_datos")
    frontera: Mapped["Frontera | None"] = relationship("Frontera", back_populates="xm_datos")


class LiquidacionMandato(Base):
    __tablename__ = "liquidacion_mandatos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    liquidacion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("liquidaciones.id"), nullable=False, index=True)
    inversionista_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyecto_inversionistas.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoMandatoEnum, name="tipo_mandato_enum"), nullable=False)
    numero_mandato: Mapped[str | None] = mapped_column(String(50), nullable=True)
    consecutivo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beneficiario_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    beneficiario_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    periodo_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoMandatoEnum, name="estado_mandato_enum"), nullable=False, default="borrador")
    fecha_generacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_envio_revisoria: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    pa_aplica: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    categoria_contable: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_ingresos_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_costos_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_retenciones_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_iva_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    valor_neto_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    liquidacion: Mapped["Liquidacion"] = relationship("Liquidacion", back_populates="mandatos")
    inversionista: Mapped["ProyectoInversionista | None"] = relationship("ProyectoInversionista")
    lineas: Mapped[List["LiquidacionMandatoLinea"]] = relationship("LiquidacionMandatoLinea", back_populates="mandato")


class LiquidacionMandatoLinea(Base):
    __tablename__ = "liquidacion_mandato_lineas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mandato_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("liquidacion_mandatos.id"), nullable=False, index=True)
    tipo_linea: Mapped[str] = mapped_column(SAEnum(TipoLineaMandatoEnum, name="tipo_linea_mandato_enum"), nullable=False)
    concepto: Mapped[str] = mapped_column(String(500), nullable=False)
    valor_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    porcentaje: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    base_calculo_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    referencia_factura: Mapped[str | None] = mapped_column(String(255), nullable=True)
    soporte_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    mandato: Mapped["LiquidacionMandato"] = relationship("LiquidacionMandato", back_populates="lineas")


class LiquidacionFactura(Base):
    __tablename__ = "liquidacion_facturas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    liquidacion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("liquidaciones.id"), nullable=False, index=True)
    proyecto_inversionista_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyecto_inversionistas.id", ondelete="SET NULL"), nullable=True, index=True)
    tipo_servicio: Mapped[str] = mapped_column(SAEnum(TipoFacturaServicioEnum, name="tipo_factura_servicio_enum"), nullable=False)
    numero_factura: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nro_soporte: Mapped[str | None] = mapped_column(String(100), nullable=True)
    soporte_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    valor_cop: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoFacturaEnum, name="estado_factura_enum"), nullable=False, default="emitida")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    liquidacion: Mapped["Liquidacion"] = relationship("Liquidacion", back_populates="facturas")
    inversionista: Mapped["ProyectoInversionista | None"] = relationship("ProyectoInversionista")


