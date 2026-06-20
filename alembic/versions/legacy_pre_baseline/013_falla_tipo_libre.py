"""Add tipo_libre to fallas and make tipo_id nullable

Revision ID: 013
Revises: 012
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allow tipo_id to be null (for custom free-text types)
    op.execute("ALTER TABLE fallas ALTER COLUMN tipo_id DROP NOT NULL")
    # Add tipo_libre for free-text fault type description
    op.execute("ALTER TABLE fallas ADD COLUMN IF NOT EXISTS tipo_libre VARCHAR(255)")


def downgrade() -> None:
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS tipo_libre")
    op.execute("UPDATE fallas SET tipo_id = (SELECT id FROM fallas_cat_tipos LIMIT 1) WHERE tipo_id IS NULL")
    op.execute("ALTER TABLE fallas ALTER COLUMN tipo_id SET NOT NULL")
