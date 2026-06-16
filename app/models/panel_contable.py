import enum
from datetime import datetime, date
from typing import List
from sqlalchemy import (
    BigInteger, String, Numeric, Boolean, Date, DateTime, Integer,
    ForeignKey, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoPanelEnum(str, enum.Enum):
    preliquidacion = "preliquidacion"
    oficial = "oficial"


class GrupoLineaEnum(str, enum.Enum):
    ingresos = "ingresos"
    comercializacion = "comercializacion"
    costos = "costos"
    facturas = "facturas"
    resultado = "resultado"


class PanelContable(Base):
    """
    Borrador contable de un proyecto para un período. Cada panel es el resultado
    de cargar un Estado de Resultados (ER) y dividirlo por inversionista.
    'preliquidacion' = estimado; 'oficial' = real. Se comparan después.
    """
    __tablename__ = "panel_contable"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", "tipo", name="uq_panel_proyecto_periodo_tipo"),
        Index("ix_panel_periodo_tipo", "periodo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="preliquidacion")

    # Liquidación de ingresos y de costos son independientes; cada una consume su
    # propia cadena de consecutivos. (liquidar se mantiene por compatibilidad.)
    liquidar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    liquidar_ingresos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    liquidar_costos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generar_mandatos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tiene_bolsa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tiene_costos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingreso_bruto_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    comercializador: Mapped[str | None] = mapped_column(String(120), nullable=True)

    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    consecutivo_ingresos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutivo_costos: Mapped[int | None] = mapped_column(Integer, nullable=True)

    er_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    generado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lineas: Mapped[List["PanelContableLinea"]] = relationship(
        "PanelContableLinea", back_populates="panel",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class TipoLiquidacionEnum(str, enum.Enum):
    normal = "normal"
    neu = "neu"
    nitro = "nitro"


class ClasificacionLiquidacion(Base):
    """
    Tipo de liquidación de un proyecto PARA UN PERÍODO concreto. Un proyecto
    puede ser NEU en enero y normal en marzo, por eso la clave es
    (proyecto_id, periodo). Sin registro → se asume 'normal'.

    El tipo determina cómo se parsea la sección de ingresos del ER:
      - normal: ingreso bruto venta de energía
      - neu:    despacho + ventas/compras bolsa + distribución superávit + ajuste
      - nitro:  ingreso bruto + ventas/compras bolsa + comercialización
    """
    __tablename__ = "clasificacion_liquidacion"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", name="uq_clasif_proyecto_periodo"),
        Index("ix_clasif_periodo", "periodo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PanelContableLinea(Base):
    """
    Una línea del detalle contable de un panel, ya dividida por inversionista.
    grupo: ingresos | comercializacion | costos | facturas | resultado
    """
    __tablename__ = "panel_contable_linea"
    __table_args__ = (
        Index("ix_panel_linea_panel", "panel_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("panel_contable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proyecto_inversionista_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyecto_inversionistas.id", ondelete="SET NULL"), nullable=True
    )
    inversionista_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    porcentaje: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)

    grupo: Mapped[str] = mapped_column(String(20), nullable=False)
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    valor_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    comprobante_contable: Mapped[str | None] = mapped_column(String(120), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    panel: Mapped["PanelContable"] = relationship("PanelContable", back_populates="lineas")
