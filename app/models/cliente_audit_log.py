"""Bitácora inmutable de propagación de cambios Cliente → PPA.

Cada fila registra un único campo que cambió en un cliente y que el job diario
propagó (o detectó) sobre un contrato PPA. Es append-only: nunca se actualiza ni
se borra, sirviendo como soporte del "Adenda Digital" (trazabilidad legal).
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class ClientePpaAuditLog(Base):
    __tablename__ = "cliente_ppa_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clientes.id"), nullable=False, index=True,
    )
    ppa_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id"), nullable=False, index=True,
    )
    field_changed: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_critical: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false",
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    triggered_by: Mapped[str] = mapped_column(
        String(50), nullable=False, default="system_job", server_default="system_job",
    )

    cliente = relationship("Cliente", foreign_keys=[cliente_id])
    contrato = relationship("PPAContrato", foreign_keys=[ppa_id])
