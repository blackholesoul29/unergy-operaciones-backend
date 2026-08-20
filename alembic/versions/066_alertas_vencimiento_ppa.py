"""Tabla `alertas` — alertas persistentes de vencimiento de contratos PPA.

Persiste una alerta por cada ventana de antelación (90/60/30 días) al fin de un
contrato PPA, generada por el job diario `app/jobs/ppa_expiration_checker.py`.
La restricción única (ppa_id, days_to_expiration) hace idempotente al job:
correrlo dos veces no duplica la alerta de la misma ventana.

`project_id` es NULLABLE: un PPA se vincula a 0..N proyectos (m2m vía
`ppa_contrato_proyectos`), por lo que puede no haber un único proyecto asociado.

IF NOT EXISTS en cada paso para que reintentar la migración desde cero sea seguro
si un deploy se corta a medias (mismo criterio que 034_maintenance_impact).

Revision ID: 064
Revises: 063
Create Date: 2026-07-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS alertas (
            id BIGSERIAL PRIMARY KEY,
            ppa_id BIGINT NOT NULL REFERENCES ppa_contratos(id) ON DELETE CASCADE,
            project_id BIGINT REFERENCES proyectos(id) ON DELETE CASCADE,
            alert_type VARCHAR(50) NOT NULL,
            description TEXT,
            due_date DATE NOT NULL,
            trigger_date DATE NOT NULL DEFAULT CURRENT_DATE,
            days_to_expiration INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'new',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_alertas_ppa_dias UNIQUE (ppa_id, days_to_expiration)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_alertas_ppa_id ON alertas (ppa_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_alertas_project_id ON alertas (project_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_alertas_project_id", table_name="alertas")
    op.drop_index("ix_alertas_ppa_id", table_name="alertas")
    op.drop_table("alertas")
