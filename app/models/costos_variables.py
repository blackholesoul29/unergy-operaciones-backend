from datetime import datetime, date
from sqlalchemy import BigInteger, String, Numeric, Date, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class CostoVariable(Base):
    __tablename__ = "costos_variables"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    tipo_accion: Mapped[str] = mapped_column(String(50), nullable=False)       # compra | poliza
    tipo_equipo: Mapped[str] = mapped_column(String(100), nullable=False)      # transformador_corriente | ...
    monto: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Documentos adjuntos — Google Drive URLs + nombre original
    url_factura: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nombre_factura: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url_cotizacion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nombre_cotizacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url_rut: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nombre_rut: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url_certificado_bancario: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nombre_certificado_bancario: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
