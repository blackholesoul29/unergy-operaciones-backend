"""Add correos_operacionales JSONB array to clientes

Revision ID: 015
Revises: 014
Create Date: 2026-06-04
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Nueva columna array de correos operacionales
    op.execute(
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correos_operacionales JSONB DEFAULT '[]'::jsonb"
    )
    # 2. Migrar correo_operacional existente al array (si tiene valor)
    op.execute("""
        UPDATE clientes
        SET correos_operacionales = jsonb_build_array(correo_operacional)
        WHERE correo_operacional IS NOT NULL
          AND correo_operacional <> ''
          AND (correos_operacionales IS NULL OR correos_operacionales = '[]'::jsonb)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS correos_operacionales")
