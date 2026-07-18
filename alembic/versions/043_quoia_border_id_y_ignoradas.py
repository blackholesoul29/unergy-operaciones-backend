"""Soporte para el panel de fronteras pendientes de Quoia.

Agrega fronteras.quoia_border_id (id interno de Quoia para
get_border_report_status(), que no acepta frt_code) y la tabla
fronteras_quoia_ignoradas, donde se registran los borders de Quoia
marcados a proposito como "no aplica" desde /fronteras/quoia/pendientes
para que dejen de aparecer como pendientes.

Revision ID: 043
Revises: 042
Create Date: 2026-07-08
"""
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS quoia_border_id INTEGER")

    op.execute("""
        CREATE TABLE IF NOT EXISTS fronteras_quoia_ignoradas (
            id BIGSERIAL PRIMARY KEY,
            frt_code VARCHAR(50) NOT NULL UNIQUE,
            motivo VARCHAR(500),
            ignorado_por_usuario_id BIGINT REFERENCES usuarios(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fronteras_quoia_ignoradas")
    op.execute("ALTER TABLE fronteras DROP COLUMN IF EXISTS quoia_border_id")
