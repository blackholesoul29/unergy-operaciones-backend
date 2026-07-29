"""Agrega 'semestral' a periodicidad_enum.

Provisionado también en main.py::_PENDING_DDLS (camino de deploy real del repo).
Idempotente (IF NOT EXISTS).

Revision ID: 050
Revises: 049
Create Date: 2026-07-22
"""
from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE periodicidad_enum ADD VALUE IF NOT EXISTS 'semestral'")


def downgrade() -> None:
    # PostgreSQL no soporta quitar un valor de un ENUM; no-op.
    pass
