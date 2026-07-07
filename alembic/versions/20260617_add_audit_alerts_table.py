"""Monitoreo proactivo de auditoría: `audit_alerts` y `audit_rules`.

`audit_alerts` guarda cada alerta disparada por `AuditMonitorService` al detectar
un cambio crítico (fuera de horario, usuario no autorizado, cambio de valor
crítico) en liquidaciones/PPA/generación, leyendo `audit_log`. `audit_rules`
permite ajustar dinámicamente umbrales/reglas por tipo de entidad.

IF NOT EXISTS en cada paso para que reintentar la migración desde cero sea seguro
si un deploy se corta a medias (mismo criterio que 033/034). Las tablas también
se aprovisionan vía Base.metadata.create_all al arranque; esta migración mantiene
la cadena Alembic alineada.

Revision ID: 20260617
Revises: 039
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260617"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_alerts (
            id BIGSERIAL PRIMARY KEY,
            rule_name VARCHAR(150) NOT NULL,
            entity_type VARCHAR(30) NOT NULL,
            entity_id VARCHAR(50) NOT NULL,
            trigger_reason TEXT NOT NULL,
            severity VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            fingerprint VARCHAR(120) NOT NULL,
            audit_log_id BIGINT,
            usuario_nombre VARCHAR(255),
            detalle JSONB,
            notificado BOOLEAN NOT NULL DEFAULT FALSE,
            acknowledged_by VARCHAR(255),
            acknowledged_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_alerts_fingerprint "
        "ON audit_alerts (fingerprint)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_alerts_entity_type ON audit_alerts (entity_type)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_alerts_severity ON audit_alerts (severity)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_alerts_created ON audit_alerts (created_at DESC)"
    ))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_rules (
            id BIGSERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            entity_type VARCHAR(30) NOT NULL,
            condition_json JSONB,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_rules_entity_type ON audit_rules (entity_type)"
    ))


def downgrade() -> None:
    op.drop_table("audit_rules")
    op.drop_table("audit_alerts")
