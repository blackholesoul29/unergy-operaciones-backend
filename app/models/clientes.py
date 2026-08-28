import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Enum as SAEnum, DateTime, Date,
                        ForeignKey, Text, UniqueConstraint, CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoPersonaEnum(str, enum.Enum):
    natural = "natural"
    juridica = "juridica"


class TipoDocumentoClienteEnum(str, enum.Enum):
    rut = "rut"
    certificado_bancario = "certificado_bancario"
    camara_comercio = "camara_comercio"
    oferta = "oferta"
    contrato = "contrato"


class EstadoDocumentoClienteEnum(str, enum.Enum):
    borrador = "borrador"
    enviado = "enviado"
    aceptado = "aceptado"
    firmado = "firmado"
    rechazado = "rechazado"


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    razon_social_nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    nit_cedula: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    tipo_persona: Mapped[str | None] = mapped_column(SAEnum(TipoPersonaEnum, name="tipo_persona_enum"), nullable=True)
    representante_legal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    iva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    retencion_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteica_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteiva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Origen comercial del cliente. VARCHAR (no enum de BD) a propósito:
    # la tabla ya existe y un tipo nuevo complicaría la migración; la
    # validación de valores vive en el schema Pydantic (OrigenClienteLiteral).
    origen_tipo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Persona que recomendó/consiguió el cliente.
    origen_detalle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    participaciones: Mapped[list["ProyectoInversionista"]] = relationship("ProyectoInversionista", back_populates="cliente", uselist=True)
    documentos_comerciales: Mapped[list["ClienteDocumentoComercial"]] = relationship("ClienteDocumentoComercial", back_populates="cliente", cascade="all, delete-orphan", uselist=True)
    contactos: Mapped[list["Contacto"]] = relationship("Contacto", back_populates="cliente", cascade="all, delete-orphan", uselist=True)


class ClienteDocumentoComercial(Base):
    """Documento genérico con archivo/enlace (RUT, cámara de comercio, carpeta
    de un contrato, etc.) -- pese al nombre (histórico, se conserva para no
    romper referencias), NO es exclusiva de Cliente: generalización
    2026-08-28 (auditoría de Clientes) para eliminar los campos sueltos
    equivalentes que tenían Cliente.rut_url, ContratoServicio.enlace_drive y
    PPAContrato.carpeta_link -- una sola tabla, un solo patrón de UI/API en
    vez de tres campos de link ad-hoc sin historial ni estado.

    Exactamente UNA de (cliente_id, contrato_servicio_id, ppa_contrato_id)
    identifica al dueño (ver CheckConstraint); las demás quedan NULL."""
    __tablename__ = "cliente_documentos_comerciales"
    __table_args__ = (
        # CAST(...AS INTEGER) y no `::int`: el cast ANSI corre igual en Postgres
        # (produccion) y SQLite (tests, create_all) -- el shorthand `::` es
        # exclusivo de Postgres y create_all() revienta con "unrecognized token".
        CheckConstraint(
            "CAST(cliente_id IS NOT NULL AS INTEGER) "
            "+ CAST(contrato_servicio_id IS NOT NULL AS INTEGER) "
            "+ CAST(ppa_contrato_id IS NOT NULL AS INTEGER) = 1",
            name="ck_documento_un_solo_dueno",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=True, index=True)
    contrato_servicio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=True, index=True)
    ppa_contrato_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoDocumentoClienteEnum, name="tipo_documento_cliente_enum"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    numero: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoDocumentoClienteEnum, name="estado_documento_cliente_enum"),
        nullable=False, default="borrador"
    )
    archivo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    archivo_nombre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Oportunidad del CRM a la que pertenece este documento (oferta/CC/RUT).
    oportunidad_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=True, index=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cliente: Mapped["Cliente | None"] = relationship("Cliente", back_populates="documentos_comerciales")
    contrato_servicio: Mapped["ContratoServicio | None"] = relationship(
        "ContratoServicio", back_populates="documentos_comerciales")
    ppa_contrato: Mapped["PPAContrato | None"] = relationship(
        "PPAContrato", back_populates="documentos_comerciales")


class ClienteTasaServicio(Base):
    """
    Excepción de tasa de impuesto por (cliente, servicio) — y opcionalmente por
    proyecto. Sobrescribe las tasas planas del cliente (iva/retencion/reteiva/
    reteica_pct) SOLO para ese servicio (Representación|CGM|Administración). Cada
    _pct null ⇒ hereda la tasa general del cliente. proyecto_id null ⇒ aplica a
    todos los proyectos del cliente; si viene, solo a ese proyecto.
    Ej.: Solenium, Administración, retencion_pct=11 (ReteFuente Adm 11% en vez de 4%).
    """
    __tablename__ = "cliente_tasa_servicio"
    __table_args__ = (
        UniqueConstraint("cliente_id", "servicio", "proyecto_id",
                         name="uq_cliente_tasa_servicio"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    servicio: Mapped[str] = mapped_column(String(30), nullable=False)
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=True
    )
    iva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    retencion_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteiva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteica_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
