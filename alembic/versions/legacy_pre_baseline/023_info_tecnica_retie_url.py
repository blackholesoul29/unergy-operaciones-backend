"""Add retie_url to proyecto_info_tecnica

Enlace al documento RETIE del proyecto (Google Drive u otro). Idempotente.

Revision ID: 023
Revises: 022
Create Date: 2026-06-17
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS retie_url TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE proyecto_info_tecnica DROP COLUMN IF EXISTS retie_url")
