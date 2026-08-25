"""Alertas persistentes -- vencimiento proactivo de contratos PPA.

A diferencia de las alertas calculadas al vuelo de `app/api/v1/alertas.py`
(huerfanos, duplicados, deficit de cumplimiento), esta tabla PERSISTE una
alerta por cada ventana de antelacion (90/60/30 dias) al fin de un contrato
PPA. El job diario `app/jobs/ppa_expiration_checker.py` la puebla y la
restriccion unica (ppa_id, days_to_expiration) garantiza idempotencia: correr
el job dos veces no duplica la alerta de la misma ventana.

`project_id` es NULLABLE a proposito: un PPA se vincula a 0..N proyectos
(relacion muchos-a-muchos via ppa_contrato_proyectos), asi que puede no haber
un unico proyecto asociado. El job estampa el primer proyecto vinculado si lo hay.

Tabla generica (no exclusiva de PPA): `alert_type` distingue el tipo, por si
aparece otra alerta proactiva mas adelante que valga la pena persistir igual.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Integer, String, Text, Date, DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ppa_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fecha de vencimiento del contrato PPA (PPAContrato.fecha_fin).
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Fecha en que se disparo la alerta (por defecto hoy).
    trigger_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date(),
    )
    days_to_expiration: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    ppa = relationship("PPAContrato", lazy="select")
    proyecto = relationship("Proyecto", lazy="select")

    __table_args__ = (
        UniqueConstraint("ppa_id", "days_to_expiration", name="uq_alertas_ppa_dias"),
    )
