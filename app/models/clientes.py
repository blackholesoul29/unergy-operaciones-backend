import enum
from datetime import datetime, date
from sqlalchemy import BigInteger, String, Numeric, Enum as SAEnum, DateTime, Date, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoPersonaEnum(str, enum.Enum):
    natural = "natural"
    juridica = "juridica"


class TipoServicioClienteEnum(str, enum.Enum):
    operacion = "operacion"
    representacion = "representacion"
    cgm = "cgm"
    promotor = "promotor"


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
    correo_liquidacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correo_monitoreo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correo_soporte: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correo_operacional: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correos_operacionales: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list, server_default="'[]'::jsonb")
    correos_cgm: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list, server_default="'[]'::jsonb")
    telefono_contacto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Banking info
    banco: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tipo_cuenta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    numero_cuenta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    titular_cuenta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    retencion_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteica_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    rut_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Origen comercial del cliente. VARCHAR (no enum de BD) a propósito:
    # la tabla ya existe y un tipo nuevo complicaría la migración; la
    # validación de valores vive en el schema Pydantic (OrigenClienteLiteral).
    origen_tipo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Persona que recomendó/consiguió el cliente.
    origen_detalle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origina_investment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    participaciones: Mapped[list["ProyectoInversionista"]] = relationship("ProyectoInversionista", back_populates="cliente", uselist=True)
    servicios: Mapped[list["ClienteServicio"]] = relationship("ClienteServicio", back_populates="cliente", cascade="all, delete-orphan", uselist=True)
    documentos_comerciales: Mapped[list["ClienteDocumentoComercial"]] = relationship("ClienteDocumentoComercial", back_populates="cliente", cascade="all, delete-orphan", uselist=True)
    contactos: Mapped[list["Contacto"]] = relationship("Contacto", back_populates="cliente", cascade="all, delete-orphan", uselist=True)


class ClienteServicio(Base):
    __tablename__ = "cliente_servicios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoServicioClienteEnum, name="tipo_servicio_cliente_enum"), nullable=False)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="servicios")


class ClienteDocumentoComercial(Base):
    __tablename__ = "cliente_documentos_comerciales"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
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
    servicio_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cliente_servicios.id", ondelete="SET NULL"), nullable=True, index=True)
    # Oportunidad del CRM a la que pertenece este documento (oferta/CC/RUT).
    oportunidad_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=True, index=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="documentos_comerciales")
    servicio: Mapped["ClienteServicio | None"] = relationship("ClienteServicio")
