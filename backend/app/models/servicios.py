import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class FrecuenciaRevisionEnum(str, enum.Enum):
    diaria = "diaria"
    semanal = "semanal"
    mensual = "mensual"


class ModalidadVentaEnum(str, enum.Enum):
    bolsa_directa = "bolsa_directa"
    bolsa_comercializador = "bolsa_comercializador"
    ppa = "ppa"
    interna = "interna"


class ServicioOperacion(Base):
    __tablename__ = "servicio_operacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    plataforma_monitoreo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url_plataforma: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usuario_acceso_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frecuencia_revision: Mapped[str | None] = mapped_column(SAEnum(FrecuenciaRevisionEnum, name="frecuencia_revision_enum"), nullable=True)
    responsable_operacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disponibilidad_garantizada_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    tarifa_mw_ano_cop: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pct_operacion_ingresos: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    sla_critico_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_grave_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_medio_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_leve_descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="servicio_operacion")
    kpis: Mapped[list] = relationship("OperacionKPI", back_populates="servicio_operacion")


class OperacionKPI(Base):
    __tablename__ = "operacion_kpis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    servicio_operacion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("servicio_operacion.id"), nullable=True)
    periodo_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fin: Mapped[date] = mapped_column(Date, nullable=False)
    energia_generada_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    energia_esperada_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    performance_ratio_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    disponibilidad_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    horas_equivalentes: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="kpis")
    servicio_operacion: Mapped["ServicioOperacion | None"] = relationship("ServicioOperacion", back_populates="kpis")


class ServicioRepresentacion(Base):
    __tablename__ = "servicio_representacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    nit_rf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nombre_rf: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    modalidad_venta: Mapped[str | None] = mapped_column(SAEnum(ModalidadVentaEnum, name="modalidad_venta_enum"), nullable=True)
    nombre_comercializador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    codigo_despacho_xm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="servicio_representacion")
    gescon_registros: Mapped[list] = relationship("RepresentacionGescon", back_populates="servicio_representacion")


class RepresentacionGescon(Base):
    __tablename__ = "representacion_gescon"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    servicio_representacion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("servicio_representacion.id"), nullable=True)
    codigo_contrato_gescon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    cantidad_pactada_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    codigos_sic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    precio_registrado: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    servicio_representacion: Mapped["ServicioRepresentacion | None"] = relationship("ServicioRepresentacion", back_populates="gescon_registros")


class ServicioCGM(Base):
    __tablename__ = "servicio_cgm"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    nit_cgm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nombre_cgm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    plataforma_captura: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frecuencia_reporte: Mapped[str] = mapped_column(String(50), default="diaria", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="servicio_cgm")
