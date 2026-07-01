"""ID estable de Sun Factory en proyectos — evita duplicados cuando Sun Factory
cambia el nombre/base_name de un proyecto entre sincronizaciones del pipeline TSF.

Revision ID: 031
Revises: 030
Create Date: 2026-07-01
"""
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deliberadamente separado de `project_id_solenium` (usado para el API de
    # generacion de Solenium, data.solenium.co) porque Sun Factory
    # (sunfactory.solenium.co) es un producto distinto con su propio espacio de
    # IDs -- aunque ambos son de Solenium, no hay garantia de que numeren igual.
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sunfactory_project_id INTEGER")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_proyectos_sunfactory_project_id "
        "ON proyectos (sunfactory_project_id) WHERE sunfactory_project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proyectos_sunfactory_project_id")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS sunfactory_project_id")
