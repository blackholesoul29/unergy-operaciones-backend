"""Add 'ranking' value to tipo_informe_enum

Permite guardar informes de tipo "Ranking vs P90". Idempotente.

Revision ID: 024
Revises: 023
Create Date: 2026-06-19
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE no puede ir dentro de un bloque de transacción.
    op.execute("COMMIT")
    op.execute("ALTER TYPE tipo_informe_enum ADD VALUE IF NOT EXISTS 'ranking'")


def downgrade() -> None:
    # Postgres no permite eliminar valores de un enum de forma simple; no-op.
    pass
