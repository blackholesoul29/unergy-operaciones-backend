"""Add coordinador and tecnico roles

Revision ID: 019
Revises: 018
Create Date: 2026-06-10
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE rol_enum ADD VALUE IF NOT EXISTS 'coordinador'")
    op.execute("ALTER TYPE rol_enum ADD VALUE IF NOT EXISTS 'tecnico'")


def downgrade() -> None:
    # PostgreSQL no soporta eliminar valores de un enum
    pass
