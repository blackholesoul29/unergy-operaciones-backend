"""Protege la fase de construcción editada a mano (mismo patrón que la fecha).

Sin esta columna, si un operador corregía el Estado a mano en la tabla de
"próximos a energizar", el siguiente sync de Sun Factory lo podía pisar de
vuelta -- a diferencia de la fecha estimada, que ya tenía esta protección.

Revision ID: 045
Revises: 044
Create Date: 2026-07-10
"""
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS "
        "fase_construccion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS fase_construccion_editada_manual")
