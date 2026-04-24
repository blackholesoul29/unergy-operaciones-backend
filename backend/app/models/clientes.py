import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Numeric, Enum as SAEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoPersonaEnum(str, enum.Enum):
    natural = "natural"
    juridica = "juridica"


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    razon_social_nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    nit_cedula: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    tipo_persona: Mapped[str | None] = mapped_column(SAEnum(TipoPersonaEnum, name="tipo_persona_enum"), nullable=True)
    representante_legal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correo_electronico: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telefono_contacto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    iva_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    retencion_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reteica_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyectos: Mapped[list] = relationship("Proyecto", back_populates="cliente")
    participaciones: Mapped[list] = relationship("ProyectoInversionista", back_populates="cliente")
