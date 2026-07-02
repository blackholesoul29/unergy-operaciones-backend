import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoSolicitudAsicEnum(str, enum.Enum):
    registro = "registro"
    modificacion = "modificacion"
    terminacion = "terminacion"
    desistimiento = "desistimiento"


class EstadoSolicitudAsicEnum(str, enum.Enum):
    en_proceso = "en_proceso"
    publicado = "publicado"
    rechazado = "rechazado"
    desistido = "desistido"
    terminado = "terminado"


class AsicSolicitud(Base):
    __tablename__ = "asic_solicitudes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    requerimiento_asic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tipo_solicitud: Mapped[str] = mapped_column(SAEnum(TipoSolicitudAsicEnum, name="tipo_solicitud_asic_enum"), nullable=False)
    prioridad_limitacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    codigo_sic_contrato: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_sic_vendedor: Mapped[str | None] = mapped_column(String(10), nullable=True)
    codigo_sic_comprador: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Cédulas de los agentes (XM las exige en una terminación; distintas del código SIC)
    cedula_agente_vendedor: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cedula_agente_comprador: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contrato_interno: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nombre_contacto_solicitante: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_solicitud: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    tipo_mercado: Mapped[str | None] = mapped_column(String(50), nullable=True, default="No regulado")
    tipo_asignacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    porcentaje_fncer: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    porcentaje_despacho: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    estado_solicitud: Mapped[str] = mapped_column(SAEnum(EstadoSolicitudAsicEnum, name="estado_solicitud_asic_enum"), nullable=False, default="en_proceso")
    nombre_interno: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_archivo: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reemplaza_anterior: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    es_duplicado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fecha_envio_xm: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_respuesta_xm: Mapped[date | None] = mapped_column(Date, nullable=True)
    numero_radicado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contrato_ppa_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ppa_contratos.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto | None"] = relationship("Proyecto", back_populates="asic_solicitudes")
    contrato_ppa: Mapped["PPAContrato | None"] = relationship("PPAContrato", foreign_keys=[contrato_ppa_id])
    cambios: Mapped[list["AsicCambioContrato"]] = relationship("AsicCambioContrato", back_populates="solicitud")


class AsicCambioContrato(Base):
    __tablename__ = "asic_cambios_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    solicitud_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("asic_solicitudes.id"), nullable=True, index=True)
    codigo_sic_contrato: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contrato_interno: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proyecto_original_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    codigo_frt_original: Mapped[str | None] = mapped_column(String(20), nullable=True)
    energia_mensual_mwh_original: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    proyecto_nuevo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    codigo_frt_nuevo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    energia_mensual_mwh_nuevo: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    accion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nombre_archivo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    solicitud: Mapped["AsicSolicitud | None"] = relationship("AsicSolicitud", back_populates="cambios")


class GesconDiccionario(Base):
    __tablename__ = "gescon_diccionario_contratos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_contrato: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
