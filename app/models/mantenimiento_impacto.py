"""Modelo de Impacto de Mantenimiento.

Registra el downtime y la energía perdida durante un evento de mantenimiento de
una planta, junto con su valoración económica y la bandera de riesgo de
penalización PPA. El vínculo opcional a `Falla` cubre el caso en que el
mantenimiento se originó a partir de una falla registrada.
"""
import enum
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import (BigInteger, String, Boolean, DateTime, Numeric, ForeignKey)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func

from app.models.base import Base


class TipoMantenimientoImpactoEnum(str, enum.Enum):
    scheduled = "scheduled"
    unscheduled = "unscheduled"


_COL_TZ = timezone(timedelta(hours=-5))  # Colombia (UTC-5)


class MantenimientoImpacto(Base):
    __tablename__ = "mantenimiento_impacto"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    # Vínculo opcional: el mantenimiento nació de una falla que derivó en intervención.
    falla_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fallas.id", ondelete="SET NULL"), nullable=True, index=True)
    maintenance_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="scheduled")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_generation_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_generation_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    lost_energy_kwh: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    financial_impact_cop: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    ppa_penalty_risk_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Sin back_populates para no acoplar Proyecto/Falla a este módulo nuevo
    # (mismo criterio que CumplimientoMensual.proyecto).
    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
    falla: Mapped["Falla | None"] = relationship("Falla")

    @hybrid_property
    def duration_hours(self) -> float | None:
        """Duración del evento (end - start) en horas. None si falta algún extremo."""
        if not self.start_time or not self.end_time:
            return None
        start = self.start_time if self.start_time.tzinfo else self.start_time.replace(tzinfo=_COL_TZ)
        end = self.end_time if self.end_time.tzinfo else self.end_time.replace(tzinfo=_COL_TZ)
        return round(max(0.0, (end - start).total_seconds() / 3600), 2)
