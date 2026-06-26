"""arr_documento: una copia por predio (arr_proyecto_id nullable + ruta_original).

Revision ID: 030
Revises: 029
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arr_documento", sa.Column("ruta_original", sa.String(1000), nullable=True))
    op.alter_column("arr_documento", "arr_proyecto_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("arr_documento", "arr_proyecto_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("arr_documento", "ruta_original")
