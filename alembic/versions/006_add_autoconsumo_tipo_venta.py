"""add autoconsumo to tipo_venta_liq_enum

Revision ID: 006
Revises: 005_ppa_many_projects
Create Date: 2026-05-07
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TYPE cannot run inside a transaction in PostgreSQL
    op.execute("ALTER TYPE tipo_venta_liq_enum ADD VALUE IF NOT EXISTS 'autoconsumo'")


def downgrade():
    # PostgreSQL does not support removing enum values; downgrade is a no-op
    pass
