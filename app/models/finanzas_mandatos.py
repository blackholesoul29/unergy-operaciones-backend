import enum
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, Integer, String, Text, Date, DateTime, Enum as SAEnum,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class TipoMandatoEnum(str, enum.Enum):
    ingreso = "ingreso"
    costo = "costo"


class EstadoFirmaEnum(str, enum.Enum):
    sin_firma = "sin_firma"
    firmado = "firmado"
    con_comentarios = "con_comentarios"


class FinanzasMandato(Base):
    """Mandato (ingreso o costo) rastreado desde el correo de la revisoria.

    Identidad logica = (proyecto, tercero, periodo, tipo). El CMU es un atributo
    que puede corregirse (se guarda cmu_anterior). Independiente de la tabla
    `mandatos` (modulo viejo de Costos).
    """
    __tablename__ = "finanzas_mandatos"
    __table_args__ = (
        UniqueConstraint("proyecto", "tercero", "periodo", "tipo",
                         name="uq_finmandato_identidad"),
        Index("ix_finmandatos_periodo", "periodo"),
        Index("ix_finmandatos_cmu", "cmu"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    proyecto: Mapped[str] = mapped_column(String(255), nullable=False)
    tercero: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    periodo: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(
        SAEnum(TipoMandatoEnum, name="tipo_mandato_fin_enum"), nullable=False)
    cmu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cmu_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoFirmaEnum, name="estado_firma_fin_enum"),
        nullable=False, default="sin_firma")
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_envio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    correo_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
