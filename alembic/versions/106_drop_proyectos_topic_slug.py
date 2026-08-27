"""proyectos.topic_slug -- eliminar columna redundante con sub_project

Mismo namespace de identificador que sub_project (verificado contra
produccion): de los 55 proyectos con ambos poblados, 0 dependian del
fallback `sub_project -> topic_slug` para tener cobertura (los 55 ya
tenian sub_project tambien). 4 pares divergian en el valor (topic_slug
desactualizado, nunca usado en la practica porque sub_project siempre
gana el COALESCE). sub_project es el identificador canonico que usa el
resto del codigo. Auditoria de Proyectos 2026-08-27.

Revision ID: 106
Revises: 105
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "topic_slug"):
        op.execute("ALTER TABLE proyectos DROP COLUMN topic_slug")


def downgrade():
    # Deliberadamente vacio: topic_slug nunca aporto cobertura real sobre
    # sub_project -- recrearla no recupera ningun dato util.
    pass
