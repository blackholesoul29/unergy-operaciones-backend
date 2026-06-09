"""Agregar url_ubicacion a proyecto_info_tecnica

Revision ID: 017
Revises: 016
Create Date: 2026-06-09
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS url_ubicacion TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE proyecto_info_tecnica DROP COLUMN IF EXISTS url_ubicacion"
    )
