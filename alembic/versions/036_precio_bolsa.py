"""Tabla precio_bolsa (módulo Riesgos de Bolsa)

Revision ID: 036
Revises: 035
Create Date: 2026-07-06
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS precio_bolsa (
            id BIGSERIAL PRIMARY KEY,
            fecha_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            precio_cop_mwh NUMERIC(10, 2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_precio_bolsa_fecha_hora "
        "ON precio_bolsa (fecha_hora)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS precio_bolsa")
