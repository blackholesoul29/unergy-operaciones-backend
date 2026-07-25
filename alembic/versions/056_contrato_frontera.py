"""Asociación muchos-a-muchos contrato de servicio ↔ frontera

El contrato es el vínculo legal; la frontera es el punto físico de medida del
que sale la energía facturada. Un contrato puede cubrir varias fronteras y una
frontera puede estar en varios contratos (ej. operación y representación sobre
la misma planta), así que el vínculo va en su propia tabla.

Revision ID: 056
Revises: 047
Create Date: 2026-07-14
"""
from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato_frontera (
            id BIGSERIAL PRIMARY KEY,
            contrato_servicio_id BIGINT NOT NULL REFERENCES contratos_servicio(id) ON DELETE CASCADE,
            frontera_id BIGINT NOT NULL REFERENCES fronteras(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_contrato_frontera UNIQUE (contrato_servicio_id, frontera_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contrato_frontera_contrato_servicio_id "
        "ON contrato_frontera (contrato_servicio_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contrato_frontera_frontera_id "
        "ON contrato_frontera (frontera_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contrato_frontera")
