"""proyectos.tipo_conexion -- eliminar columna sin adopcion

No confundir con contratos_servicio.tipo_conexion (tipo de conexion de
Internet -- fibra/satelite/etc, columna distinta, sigue viva y en uso real
en ContratoServicioWizard.vue/OperacionView.vue). Esta era tipo de conexion
electrica al punto de conexion, 0/194 poblada, sin ningun input en el
frontend -- su unico consumidor era comercial.py::_ficha_tecnica(), expuesta
bajo detalles.tecnica.tipo_conexion, y ese sub-objeto no se lee en ningun
lado del frontend. Auditoria de Proyectos 2026-08-27.

Revision ID: 107
Revises: 106
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "tipo_conexion"):
        op.execute("ALTER TABLE proyectos DROP COLUMN tipo_conexion")


def downgrade():
    # Deliberadamente vacio: la columna estaba vacia (0/194) y sin ningun
    # input en el frontend -- recrearla no recupera ningun dato util.
    pass
