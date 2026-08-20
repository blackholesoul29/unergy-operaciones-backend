"""Alertas persistentes — vencimiento proactivo de contratos PPA.

A diferencia de las alertas calculadas al vuelo de `app/api/v1/alertas.py`
(huérfanos, duplicados, déficit de cumplimiento), esta tabla PERSISTE una
alerta por cada ventana de antelación (90/60/30 días) al fin de un contrato
PPA. El job diario `app/jobs/ppa_expiration_checker.py` la puebla y la
restricción única (ppa_id, days_to_expiration) garantiza idempotencia: correr
el job dos veces no duplica la alerta de la misma ventana.

`project_id` es NULLABLE a propósito: un PPA se vincula a 0..N proyectos
(relación muchos-a-muchos vía `ppa_contrato_proyectos`), así que puede no haber
un único proyecto asociado. El job estampa el primer proyecto vinculado si lo hay.
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
    # Fecha en que se disparó la alerta (por defecto hoy).
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
