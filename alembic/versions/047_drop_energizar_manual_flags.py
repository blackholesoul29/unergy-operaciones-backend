"""Elimina las marcas de edición manual del pipeline "próximos a energizar"

La pestaña ya no permite editar Proyecto/Estado/Energización/MWh a mano: todo
viene tal cual de Sun Factory. Sin forma de marcarlas en True, estas dos
columnas quedaron muertas (ver app/services/tsf_sync.py, que ya no las lee).

Revision ID: 047
Revises: 046
Create Date: 2026-07-11
"""
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS fase_construccion_editada_manual")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS fecha_estimada_editada_manual")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS "
        "fase_construccion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS "
        "fecha_estimada_editada_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )
