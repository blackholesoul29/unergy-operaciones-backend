"""Datos crudos de liquidación XM ingeridos desde archivos Excel.

OJO — no confundir con `LiquidacionXMDato` (tabla `liquidacion_xm_datos`) del
módulo `app.models.liquidaciones`, que es el detalle de FACTURACIÓN por frontera
vinculado a una `Liquidacion`. Este modelo es distinto: almacena filas crudas
provenientes de los archivos que publica XM (`listado_recursos.xlsx`,
`generacion_distribuida.xlsx`), como insumo del pipeline de ingesta automática.

Por eso la clase se llama `LiquidacionXMDatoIngesta` y la tabla `liquidacion_xm_dato`
(singular), para no colisionar con el modelo preexistente en el registry de
SQLAlchemy ni con la tabla `liquidacion_xm_datos`.
"""
from datetime import datetime, date
from sqlalchemy import BigInteger, String, Numeric, Date, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class LiquidacionXMDatoIngesta(Base):
    __tablename__ = "liquidacion_xm_dato"
    __table_args__ = (
        Index("uq_liquidacion_xm_dato_hash", "hash_fila", unique=True),
        Index("ix_liquidacion_xm_dato_recurso_fecha", "codigo_recurso", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Identificación del recurso
    codigo_recurso: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    agente: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo_recurso: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Datos de generación / liquidación
    capacidad_efectiva_neta_mw: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    generacion_kwh: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    precio_liquidacion_cop_kwh: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    valor_liquidacion_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Metadatos de ingesta
    fuente_archivo: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha_ingesta: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hash_fila: Mapped[str] = mapped_column(String(64), nullable=False)
