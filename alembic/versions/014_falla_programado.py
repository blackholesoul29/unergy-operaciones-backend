"""Add estado programado + fecha_programada to fallas

Revision ID: 014
Revises: 013
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Nueva columna fecha_programada en fallas
    op.execute(
        "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS fecha_programada DATE"
    )

    # 2. Insertar estado "Programado" si no existe
    op.execute("""
        INSERT INTO fallas_cat_estados (codigo, etiqueta, color_hex, orden, es_estado_final)
        VALUES ('programado', 'Programado', '#3B82F6', 0, false)
        ON CONFLICT (codigo) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS fecha_programada")
    op.execute("DELETE FROM fallas_cat_estados WHERE codigo = 'programado'")
