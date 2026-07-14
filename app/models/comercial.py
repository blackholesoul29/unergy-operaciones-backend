import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Boolean, Date, DateTime,
                        ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoOportunidadEnum(str, enum.Enum):
    prospeccion = "prospeccion"
    oferta = "oferta"
    negociacion = "negociacion"
    servicio_operativo = "servicio_operativo"   # antes 'fin' (renombrado 2026-07-13)


class TipoServicioOportunidadEnum(str, enum.Enum):
    representacion = "representacion"
    comunidad_energetica = "comunidad_energetica"


class TipoOfertaComercialEnum(str, enum.Enum):
    """Tipo de sub-oferta dentro de una oportunidad-cliente."""
    servicios_operacionales = "servicios_operacionales"
    compra_energia = "compra_energia"
    comunidad_energetica = "comunidad_energetica"


class ResultadoOfertaEnum(str, enum.Enum):
    pendiente = "pendiente"
    aceptado = "aceptado"
    declinado = "declinado"


class TipoGestionEnum(str, enum.Enum):
    llamada = "llamada"
    correo = "correo"
    reunion = "reunion"
    whatsapp = "whatsapp"
    nota = "nota"


class Oportunidad(Base):
    """Unidad del pipeline comercial. Etapa PREVIA al flujo de operación:
    apunta al Cliente existente y agrupa proyectos/oferta/contratos de UN
    negocio. Un cliente puede tener varias oportunidades en el tiempo."""

    __tablename__ = "oportunidades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
    # Etiqueta del negocio; si NULL la UI muestra la razón social del cliente.
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tipo_servicio: Mapped[str | None] = mapped_column(
        SAEnum(TipoServicioOportunidadEnum, name="tipo_servicio_oportunidad_enum"), nullable=True)
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoOportunidadEnum, name="estado_oportunidad_enum"),
        nullable=False, default="prospeccion")
    # Timestamp de la última transición de estado — base del contador de alerta.
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Consecutivo manual por ahora (automatización = futuro explícito).
    numero_oferta: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_tentativa_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_tentativa_inicio_compra_energia: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Manual por ahora (cálculo automático = futuro explícito).
    fecha_estimada_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True solo para las creadas por el backfill de clientes históricos.
    es_migrada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    creado_por_usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cliente: Mapped["Cliente"] = relationship("Cliente")
    gestiones: Mapped[list["OportunidadGestion"]] = relationship(
        "OportunidadGestion", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="desc(OportunidadGestion.fecha)")
    historial: Mapped[list["OportunidadEstadoHistorial"]] = relationship(
        "OportunidadEstadoHistorial", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="desc(OportunidadEstadoHistorial.created_at)")
    proyectos: Mapped[list["Proyecto"]] = relationship(
        "Proyecto", primaryjoin="Proyecto.oportunidad_id == Oportunidad.id",
        foreign_keys="Proyecto.oportunidad_id", uselist=True, viewonly=True)
    documentos: Mapped[list["ClienteDocumentoComercial"]] = relationship(
        "ClienteDocumentoComercial",
        primaryjoin="ClienteDocumentoComercial.oportunidad_id == Oportunidad.id",
        foreign_keys="ClienteDocumentoComercial.oportunidad_id", uselist=True, viewonly=True)
    ofertas: Mapped[list["OportunidadOferta"]] = relationship(
        "OportunidadOferta", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="OportunidadOferta.id")


class OportunidadEstadoHistorial(Base):
    """Una fila por transición de estado (y una al crear, con anterior=NULL)."""

    __tablename__ = "oportunidad_estado_historial"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    estado_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado_nuevo: Mapped[str] = mapped_column(String(20), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="historial")


class OportunidadGestion(Base):
    """Bitácora comercial (llamada/correo/reunión/whatsapp/nota). Registrar
    una gestión reinicia el contador de la alerta de N días sin respuesta."""

    __tablename__ = "oportunidad_gestiones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoGestionEnum, name="tipo_gestion_enum"), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    # Editable: permite registrar hoy una llamada que fue ayer.
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="gestiones")


class OportunidadOferta(Base):
    """Sub-oferta = una planta × un tipo de servicio dentro de la oportunidad-cliente.
    Cada fila de las hojas de prospección (Servicios / Energía / Comunidad) es una
    de estas. La oportunidad es del cliente; sus ofertas cuelgan aquí con su propio
    consecutivo, precio y resultado (aceptado/declinado)."""

    __tablename__ = "oportunidad_ofertas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoOfertaComercialEnum, name="tipo_oferta_comercial_enum"), nullable=False)
    planta_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proyecto_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    numero_oferta: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    precio_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    resultado: Mapped[str] = mapped_column(
        SAEnum(ResultadoOfertaEnum, name="resultado_oferta_enum"),
        nullable=False, default="pendiente", server_default="pendiente")
    etapa_texto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_oferta: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_tentativa_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    contrato_firmado: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Detalle crudo de la hoja de origen: para servicios_operacionales incluye
    # {servicios: [...], servicios_texto, fpo}; extensible por tipo de oferta.
    detalle: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="ofertas")
