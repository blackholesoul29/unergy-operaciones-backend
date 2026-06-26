"""Crear tabla xm_generation_history (histórico de generación XM / SinergoX)

Revision ID: 031
Revises: 030
Create Date: 2026-06-26
"""
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS xm_generation_history (
            id                BIGSERIAL PRIMARY KEY,
            proyecto_id       BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            meter_id          VARCHAR(100) NOT NULL,
            measurement_date  TIMESTAMP NOT NULL,
            generation_mwh    NUMERIC(18, 6) NOT NULL,
            source_file       VARCHAR(255),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_xm_gen_hist_proj_date_meter
                UNIQUE (proyecto_id, measurement_date, meter_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_xm_gen_hist_proj_date "
        "ON xm_generation_history (proyecto_id, measurement_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS xm_generation_history")
