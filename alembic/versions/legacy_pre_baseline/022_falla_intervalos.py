"""Add fallas_intervalos table (intervalos de disparo / trazabilidad)

Permite agrupar varios disparos del mismo proyecto bajo una sola falla,
guardando el inicio y fin exactos de cada afectación. El tiempo total de
afectación de la falla es la suma de las duraciones de sus intervalos.

Revision ID: 022
Revises: 021
Create Date: 2026-06-16
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fallas_intervalos (
            id          BIGSERIAL PRIMARY KEY,
            falla_id    BIGINT NOT NULL REFERENCES fallas(id),
            inicio      TIMESTAMPTZ NOT NULL,
            fin         TIMESTAMPTZ,
            nota        TEXT,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fallas_intervalos_falla_id ON fallas_intervalos (falla_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fallas_intervalos")
