from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


ENTITY_TYPES = (
    "cliente", "proyecto", "proyecto_ingenieria", "servicio_operacion",
    "servicio_representacion", "cgm", "ppa_contrato", "contrato_servicio",
    "contrato_arriendo", "frontera", "equipo", "promotor_seguimiento",
    "rec_proceso", "falla", "mantenimiento", "liquidacion",
    "liquidacion_mandato", "liquidacion_mandato_linea",
    "liquidacion_costo", "liquidacion_factura",
)


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(500), nullable=False)
    ruta_almacenamiento: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_id_drive: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tamano_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cargado_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_documentos_entity", "entity_type", "entity_id"),
    )
