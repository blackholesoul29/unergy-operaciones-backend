"""proyectos_pendientes_ignorados.motivo -- eliminar columna sin adopcion

Mismo caso ya resuelto para fronteras_quoia_ignoradas.motivo (migracion 097):
el frontend llama a POST /proyectos/pendientes/{clave}/ignorar sin body
(ProyectosListView.vue), asi que nunca hubo un input para diligenciarlo --
0/24 filas pobladas. Se simplifica tambien el endpoint (ya no recibe body).

Auditoria de Proyectos 2026-08-27.

Revision ID: 110
Revises: 109
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos_pendientes_ignorados", "motivo"):
        op.execute("ALTER TABLE proyectos_pendientes_ignorados DROP COLUMN motivo")


def downgrade():
    # Deliberadamente vacio: la columna estaba vacia (0/24) -- recrearla no
    # recupera ningun dato util.
    pass
