"""Tablas del Modelo Predictivo de Garantías.

Formato largo único para los insumos (`xm_medida`) con procedencia por archivo
(`xm_archivo`), más las tablas de cálculo y targets. Ver el spec §5.

Append-only por construcción: la versión de liquidación entra en la clave natural,
así que un TXR que corrige un TX2 crea una fila nueva y nunca pisa la anterior.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class XMArchivo(Base):
    """Un registro por archivo ingerido. Acá vive el anti-leakage."""
    __tablename__ = "xm_archivo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    nombre_archivo: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    periodo_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    # El filtro anti-leakage. `observado` = timestamp real de descarga;
    # `derivado` = regla de publicación aplicada en el backfill histórico.
    disponible_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origen_disponibilidad: Mapped[str] = mapped_column(String(12), nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    bytes_len: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    filas_ingeridas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    esquema_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    esquema_detalle: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ingerido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class XMMedida(Base):
    """Formato largo: todos los tipos en la misma forma."""
    __tablename__ = "xm_medida"
    __table_args__ = (
        UniqueConstraint("tipo", "fecha_documento", "hora", "entidad", "concepto",
                         "version", name="uq_xm_medida_natural"),
        Index("ix_xm_medida_tipo_fecha_ver", "tipo", "fecha_documento", "version"),
        Index("ix_xm_medida_entidad_concepto", "entidad", "concepto", "fecha_documento"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    archivo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("xm_archivo.id", ondelete="RESTRICT"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    fecha_documento: Mapped[date] = mapped_column(Date, nullable=False)
    # 0 = medida no horaria (ej. arrpas), 1-24 = hora del dia. Se usa 0 como
    # centinela en vez de NULL porque Postgres no trata dos NULL como iguales
    # en un UNIQUE, lo que rompería la idempotencia de uq_xm_medida_natural.
    hora: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    entidad: Mapped[str] = mapped_column(String(60), nullable=False)
    concepto: Mapped[str] = mapped_column(String(120), nullable=False)
    concepto_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    valor: Mapped[float] = mapped_column(Numeric(22, 6), nullable=False)
    version: Mapped[str | None] = mapped_column(String(10), nullable=True)


class GarCalculo(Base):
    """La ventana temporal de un cálculo. El período va en la clave a propósito:
    un vencimiento cubre uno o dos períodos y colapsarlos da un número que no cuadra."""
    __tablename__ = "gar_calculo"
    __table_args__ = (
        UniqueConstraint("agente", "esquema", "fecha_vencimiento", "periodo_ini",
                         "periodo_fin", name="uq_gar_calculo_natural"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Sin index=True: `agente` es la columna líder de uq_gar_calculo_natural,
    # que ya cubre ese acceso por la regla de prefijo izquierdo.
    agente: Mapped[str] = mapped_column(String(10), nullable=False)
    esquema: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fecha_calculo: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_ini: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fin: Mapped[date] = mapped_column(Date, nullable=False)
    etiqueta_periodo: Mapped[str | None] = mapped_column(String(40), nullable=True)

    base_30d_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_30d_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_sem_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_sem_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    procedencia: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discrepancias: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GarComponenteReal(Base):
    """Target: lo que XM publicó, por componente."""
    __tablename__ = "gar_componente_real"
    __table_args__ = (
        UniqueConstraint("calculo_id", "componente", name="uq_gar_comp_real"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Sin index=True: `calculo_id` es la columna líder de uq_gar_comp_real,
    # que ya cubre ese acceso por la regla de prefijo izquierdo.
    calculo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("gar_calculo.id", ondelete="CASCADE"), nullable=False)
    componente: Mapped[str] = mapped_column(String(80), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)


class GarComponentePred(Base):
    """Predicción, con el horizonte y el cuantil en la clave."""
    __tablename__ = "gar_componente_pred"
    __table_args__ = (
        UniqueConstraint("calculo_id", "componente", "horizonte_dias", "cuantil",
                         "modelo_version", name="uq_gar_comp_pred"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Sin index=True: `calculo_id` es la columna líder de uq_gar_comp_pred,
    # que ya cubre ese acceso por la regla de prefijo izquierdo.
    calculo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("gar_calculo.id", ondelete="CASCADE"), nullable=False)
    componente: Mapped[str] = mapped_column(String(80), nullable=False)
    horizonte_dias: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cuantil: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    modelo_version: Mapped[str] = mapped_column(String(40), nullable=False)
    insumos: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
