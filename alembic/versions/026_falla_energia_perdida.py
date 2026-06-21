"""Add energia_perdida_kwh to fallas

NOTA: el esquema de producción se provisiona vía _PENDING_DDLS en app/main.py
(Alembic está roto: heads múltiples). Esta migración es solo de registro.

Revision ID: 026
Revises: 025
Create Date: 2026-06-21
"""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS energia_perdida_kwh NUMERIC(14,3)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS energia_perdida_kwh")
