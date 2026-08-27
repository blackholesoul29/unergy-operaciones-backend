"""portafolios: eliminar descripcion (sin uso)

Auditoria de Proyectos 2026-08-27. El backend la aceptaba en create/update
y la devolvia en la respuesta, pero PortafoliosGestionPanel.vue (la unica
vista de gestion -- crear capa, renombrar, drag-and-drop de proyectos,
eliminar) nunca la mostro ni la edito. 0/24 portafolios en produccion
tienen descripcion cargada.

Revision ID: 119
Revises: 118
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "119"
down_revision = "118"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "portafolios", "descripcion"):
        op.execute("ALTER TABLE portafolios DROP COLUMN descripcion")


def downgrade():
    # 0/24 poblado siempre: no hay nada que valga la pena recrear.
    pass
