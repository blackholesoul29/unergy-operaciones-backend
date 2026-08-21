"""
Modelo de cumplimiento mensual PPA.

Almacena snapshots mensuales de cumplimiento de contratos PPA:
generacion real vs. compromiso, compras/excedentes en bolsa,
y su valoracion en COP.
"""
import enum
from datetime import datetime
from sqlalchemy import (
    BigInteger, Integer, Numeric, String, DateTime,
    ForeignKey, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoCumplimientoEnum(str, enum.Enum):
    pendiente = "pendiente"
    cerrado = "cerrado"
    facturado = "facturado"


class CumplimientoMensual(Base):
    __tablename__ = "cumplimiento_mensual"
    __table_args__ = (
        UniqueConstraint(
            "contrato_ppa_id", "anio", "mes",
            name="uq_cumplimiento_contrato_periodo",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contrato_ppa_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    gen_total_mwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    compromiso_mwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    compras_bolsa_mwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    excedentes_bolsa_mwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    precio_bolsa_promedio: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    compras_bolsa_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    excedentes_bolsa_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoCumplimientoEnum, name="estado_cumplimiento_enum"),
        nullable=False, default="pendiente",
    )
    tarifa_ppa_cop_mwh: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    valoracion_contrato_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    liquidacion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("liquidaciones.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Origen del cálculo: 'manual' (cerrar-periodo desde la UI) o 'automatico'
    # (pipeline mensual). Permite distinguir/depurar los snapshots del scheduler.
    origen: Mapped[str] = mapped_column(String, nullable=False, server_default="manual", default="manual")
    # Momento del último recálculo (se estampa en cada corrida del pipeline).
    fecha_calculo: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    contrato_ppa: Mapped["PPAContrato"] = relationship("PPAContrato")
    proyecto: Mapped["Proyecto | None"] = relationship("Proyecto")
    liquidacion: Mapped["Liquidacion | None"] = relationship("Liquidacion")
    # Datos XM (por frontera) generados por el pipeline a partir de este snapshot.
    liquidaciones_xm: Mapped[list["LiquidacionXMDato"]] = relationship(
        "LiquidacionXMDato", back_populates="cumplimiento",
    )
