"""Tabla de ignorados para el panel de proyectos pendientes.

Candidatos de Sun Factory/Quoia/Solenium marcados a proposito como "no
aplica" desde /proyectos/pendientes, para que dejen de aparecer como
pendientes.

Revision ID: 044
Revises: 043
Create Date: 2026-07-08
"""
from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS proyectos_pendientes_ignorados (
            id BIGSERIAL PRIMARY KEY,
            clave VARCHAR(120) NOT NULL UNIQUE,
            motivo VARCHAR(500),
            ignorado_por_usuario_id BIGINT REFERENCES usuarios(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proyectos_pendientes_ignorados")
