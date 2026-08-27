"""proyectos.nombre_bitacora / nombre_clientes -- eliminar columnas sin adopcion

Alias del nombre comercial pensados para matching/display ("nombre de
bitacora" vs. "nombre de cara al cliente") -- se leian activamente en 6+
lugares del backend (matching de nombres, monitoreo, informes de O&M), pero
nunca existio un formulario para diligenciarlos: 0/194 proyectos poblados.
En la practica cada fallback `nombre_clientes or nombre_comercial` nunca
tuvo nada distinto que priorizar. Auditoria de Proyectos 2026-08-27,
decision de eliminar en vez de construir el formulario que faltaba.

Revision ID: 105
Revises: 104
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "nombre_bitacora"):
        op.execute("ALTER TABLE proyectos DROP COLUMN nombre_bitacora")
    if columna_existe(bind, "proyectos", "nombre_clientes"):
        op.execute("ALTER TABLE proyectos DROP COLUMN nombre_clientes")


def downgrade():
    # Deliberadamente vacio: las columnas estaban vacias (0/194) desde
    # siempre -- recrearlas no recupera ningun dato.
    pass
