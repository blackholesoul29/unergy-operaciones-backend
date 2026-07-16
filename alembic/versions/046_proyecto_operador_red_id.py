"""Vínculo estructurado de operador de red también en proyectos.

Hasta ahora solo `fronteras.operador_red_id` existía (y sin ninguna forma de
editarlo desde la API) -- `proyectos.operador_red` era texto libre, sin
relación con el catálogo. Esto agrega el mismo vínculo en proyectos para
poder sincronizarlos entre sí y dejar de depender de texto libre.

Revision ID: 046
Revises: 045
Create Date: 2026-07-10
"""
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS "
        "operador_red_id BIGINT REFERENCES operadores_red(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyectos_operador_red_id ON proyectos (operador_red_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proyectos_operador_red_id")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS operador_red_id")
