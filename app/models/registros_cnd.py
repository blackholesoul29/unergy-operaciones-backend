"""Modelos de la seccion "Registros CND/ASIC".

Seguimiento del proceso de conexion de proyectos GD/AGGE ante el OR, XM (CND) y el
ASIC (desde CREG 174 hasta el requisito 9.4). Se ancla al Proyecto existente de la
plataforma (relacion 1:1 via proyecto_id); todo lo especifico del proceso vive aqui.

Los "enums" del dominio (etapa, estado, hito, tipo de documento/equipo/alerta,
responsable) se guardan como String y se validan en la capa de servicio
(app/services/registros_cnd/) — mismo criterio del prototipo: evita el manejo de
tipos enum de PostgreSQL y deja libertad para las etapas/estados futuros.

Todas las tablas se crean por Base.metadata.create_all en el arranque; no se altera
ninguna tabla existente (no se toca _PENDING_DDLS).
"""

from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, Boolean, Date, DateTime, Integer, Float, Text,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class RegistroConexion(Base):
    """Registro de seguimiento del proceso de conexion (1:1 con un Proyecto)."""

    __tablename__ = "registro_conexion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # Identificacion / tramite (no existen en proyectos)
    numero_expediente: Mapped[str | None] = mapped_column(String(100), nullable=True)
    id_requerimiento_or: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_solicitud_appweb: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Fechas del proceso
    fecha_conexion_estimada: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigencia_aprobacion_conexion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_visita_protecciones: Mapped[date | None] = mapped_column(Date, nullable=True)
    tipo_visita_protecciones: Mapped[str | None] = mapped_column(String(20), nullable=True)  # VIRTUAL|PRESENCIAL
    # Reglas operativas (alertas)
    exporta: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    comercializador_es_or: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Punto de conexion en texto (para etapa temprana, antes de existir una frontera)
    punto_conexion_texto: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relacion unidireccional a Proyecto (no se modifica proyectos.py)
    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
    etapas: Mapped[list["RegistroEtapa"]] = relationship(
        "RegistroEtapa", back_populates="registro", cascade="all, delete-orphan"
    )
    hitos: Mapped[list["RegistroHito"]] = relationship(
        "RegistroHito", back_populates="registro", cascade="all, delete-orphan"
    )
    parametros_93: Mapped["RegistroParametros93 | None"] = relationship(
        "RegistroParametros93", back_populates="registro", cascade="all, delete-orphan", uselist=False
    )
    equipos: Mapped[list["RegistroEquipoFrontera"]] = relationship(
        "RegistroEquipoFrontera", back_populates="registro", cascade="all, delete-orphan"
    )
    documentos: Mapped[list["RegistroDocumento"]] = relationship(
        "RegistroDocumento", back_populates="registro", cascade="all, delete-orphan"
    )
    alertas: Mapped[list["RegistroAlerta"]] = relationship(
        "RegistroAlerta", back_populates="registro", cascade="all, delete-orphan"
    )


class RegistroEtapa(Base):
    """Estado actual de una etapa del proceso para un registro."""

    __tablename__ = "registro_etapa"
    __table_args__ = (UniqueConstraint("registro_id", "etapa", name="uq_registro_etapa"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    etapa: Mapped[str] = mapped_column(String(50), nullable=False)
    estado_actual: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha_estado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    bloqueada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    causa_bloqueo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responsable_actual: Mapped[str | None] = mapped_column(String(30), nullable=True)

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="etapas")
    transiciones: Mapped[list["RegistroTransicion"]] = relationship(
        "RegistroTransicion", back_populates="etapa", cascade="all, delete-orphan"
    )


class RegistroTransicion(Base):
    """Historial de transiciones de estado de una etapa."""

    __tablename__ = "registro_transicion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    etapa_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_etapa.id", ondelete="CASCADE"), nullable=False, index=True
    )
    de_estado: Mapped[str | None] = mapped_column(String(50), nullable=True)
    a_estado: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nota: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evidencia_documento_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("registro_documento.id", ondelete="SET NULL"), nullable=True
    )

    etapa: Mapped["RegistroEtapa"] = relationship("RegistroEtapa", back_populates="transiciones")


class RegistroHito(Base):
    """Hito 1a..8c con su peso configurable y estado de completado."""

    __tablename__ = "registro_hito"
    __table_args__ = (UniqueConstraint("registro_id", "hito", name="uq_registro_hito"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hito: Mapped[str] = mapped_column(String(10), nullable=False)  # "1a".."8c"
    peso_pct: Mapped[float] = mapped_column(Float, nullable=False)
    completado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fecha_completado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidencia_documento_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("registro_documento.id", ondelete="SET NULL"), nullable=True
    )

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="hitos")


class RegistroParametros93(Base):
    """Parametros del requisito 9.3 (Anexo 4). 1:1 con el registro."""

    __tablename__ = "registro_parametros_93"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # Planta / unidad equivalente
    numero_unidades_equivalentes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    potencia_nominal_inversor_ac_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimo_tecnico_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    arranque_autonomo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    acuerdo_conexion_compartida: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Voltajes (kV)
    voltaje_max_kv: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltaje_nominal_kv: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltaje_min_kv: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Frecuencias (Hz) — CNO 1749
    frecuencia_max_hz: Mapped[float | None] = mapped_column(Float, nullable=True, server_default="63")
    frecuencia_min_hz: Mapped[float | None] = mapped_column(Float, nullable=True, server_default="57")
    impedancia_equivalente_ohm: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Corrientes de cortocircuito (kA / kAp)
    icc_subtrans_pico_kap: Mapped[float | None] = mapped_column(Float, nullable=True)
    icc_subtrans_3f_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    icc_subtrans_2f_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    icc_subtrans_1f_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    icc_estado_estable_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_eq_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    coef_derrateo_altura: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Protecciones (9.4, futuro): lista {funcion_ansi, etapa, ajuste, unidad, temporizacion_s}
    ajustes_protecciones: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="parametros_93")


class RegistroEquipoFrontera(Base):
    """Equipo de frontera (medidor, TC, TP, modem...) y sus fechas."""

    __tablename__ = "registro_equipo_frontera"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # MEDIDOR_PRINCIPAL, TC, TP, MODEM...
    marca: Mapped[str | None] = mapped_column(String(120), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_solicitud_solenium: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_envio_quoia: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_parametrizacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_envio_or: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_vencimiento_calibracion: Mapped[date | None] = mapped_column(Date, nullable=True)

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="equipos")


class RegistroDocumento(Base):
    """Documento / evidencia del proceso (carta, CREG 174, radicado...)."""

    __tablename__ = "registro_documento"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)  # CREG_174, AMBITO, CARTA_9_1...
    radicado: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_emision: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    firmado_por: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url_drive: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="BORRADOR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="documentos")


class RegistroAlerta(Base):
    """Alerta generada por el motor de alertas del proceso (dedupe por clave)."""

    __tablename__ = "registro_alerta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    registro_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("registro_conexion.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    fecha_disparo: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    registro: Mapped["RegistroConexion"] = relationship("RegistroConexion", back_populates="alertas")
