import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, ForeignKey, Enum as SAEnum, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ServicioAplicaEnum(str, enum.Enum):
    operacion = "operacion"
    representacion = "representacion"
    cgm = "cgm"
    promotor = "promotor"


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


class TipoContratoVentaEnum(str, enum.Enum):
    venta = "venta"
    compra = "compra"


class ContratoServicio(Base):
    __tablename__ = "contratos_servicio"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    numero_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    servicio_aplica: Mapped[str] = mapped_column(SAEnum(ServicioAplicaEnum, name="servicio_aplica_enum"), nullable=False)
    contratante_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contratante_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prestador_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prestador_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
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


class PPAContrato(Base):
    __tablename__ = "ppa_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    numero_codigo_contrato: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo_contrato: Mapped[str | None] = mapped_column(SAEnum(TipoContratoVentaEnum, name="tipo_contrato_venta_enum"), nullable=True)
    contraparte_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contraparte_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    tarifa_base: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    indice_indexacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    periodicidad_indexacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cantidad_minima_kwh_mes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    cantidad_maxima_kwh_mes: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    periodicidad_facturacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    condiciones_pago: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Datos Gescon (condiciones operativas reales)
    gescon_codigo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gescon_fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    gescon_fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    gescon_precio: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    gescon_cantidades_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    gescon_codigos_sic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="ppa_contratos")


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
