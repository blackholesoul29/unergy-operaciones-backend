"""Alertas de auditoría proactiva — `audit_alerts` y `audit_rules`.

`AuditAlert` guarda cada alerta disparada por `AuditMonitorService` al detectar
un cambio crítico en liquidaciones, PPA o generación (ver `services/audit.py` y
`services/audit_rules.py`). `AuditRule` permite ajustar dinámicamente los
umbrales/reglas por tipo de entidad sin redeploy.

Se usan columnas VARCHAR (no ENUM de Postgres) a propósito: los valores válidos
viven en las constantes de abajo, y así evitamos el dolor de `ALTER TYPE … ADD
VALUE` en la cadena de migraciones (mismo criterio que otras tablas nuevas).
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base

# Tipos de entidad monitoreada (audit_log.tabla → entity_type)
ENTITY_TYPES = ("liquidacion", "ppa", "generacion")

# Razones por las que se dispara una alerta
TRIGGER_OUTSIDE_HOURS = "outside_hours"
TRIGGER_UNAUTHORIZED_USER = "unauthorized_user"
TRIGGER_CRITICAL_VALUE = "critical_value"
TRIGGER_REASONS = (TRIGGER_OUTSIDE_HOURS, TRIGGER_UNAUTHORIZED_USER, TRIGGER_CRITICAL_VALUE)

# Severidades
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_CRITICAL = "critical"
SEVERITIES = (SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_CRITICAL)

# Estados del ciclo de vida de la alerta
STATUS_PENDING = "pending"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUSES = (STATUS_PENDING, STATUS_ACKNOWLEDGED)


class AuditAlert(Base):
    __tablename__ = "audit_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_name: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING)

    # Trazabilidad + anti-duplicados. `fingerprint` es único: garantiza que un
    # mismo registro de audit_log no genere dos veces la misma alerta.
    fingerprint: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    audit_log_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    usuario_nombre: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detalle: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    notificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )


class AuditRule(Base):
    __tablename__ = "audit_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # condition_json — override dinámico de umbrales / razones activas, p.ej.
    # {"critical_value_cop": 20000000, "critical_pct": 0.05,
    #  "reasons": ["outside_hours", "critical_value"]}
    condition_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
