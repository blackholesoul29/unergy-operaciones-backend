"""proyectos.carpeta_drive_codigo -- eliminar columna sin adopcion

Editable en 3 vistas del frontend (detalle, crear proyecto, Servicios
unificados) pero 0/194 proyectos lo usaron nunca -- a diferencia de
nombre_bitacora/topic_slug/tipo_conexion, esta no era un problema de "nadie
construyo el formulario": el formulario existia y funcionaba, simplemente el
equipo nunca adopto el flujo de vincular una carpeta de Drive por proyecto.
Decision de producto (no hallazgo tecnico), confirmada con el usuario
2026-08-27: eliminar en vez de dejarla a la espera de que se empiece a usar.

Auditoria de Proyectos 2026-08-27.

Revision ID: 108
Revises: 107
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "carpeta_drive_codigo"):
        op.execute("ALTER TABLE proyectos DROP COLUMN carpeta_drive_codigo")


def downgrade():
    # Deliberadamente vacio: la columna estaba vacia (0/194) -- recrearla
    # no recupera ningun dato util.
    pass
