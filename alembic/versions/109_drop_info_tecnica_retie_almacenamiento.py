"""proyecto_info_tecnica: eliminar retie_url y el grupo de almacenamiento

retie_url, tiene_almacenamiento, capacidad_almacenamiento_kwh,
marca_almacenamiento, modelo_almacenamiento -- las 5 en 0/110 fichas
tecnicas, pese a tener formulario editable completo en
ProyectoDetailView.vue (retie_url: input de URL; almacenamiento: checkbox +
3 campos condicionales). Mismo patron que carpeta_drive_codigo -- decision
de producto confirmada con el usuario 2026-08-27: eliminar en vez de
esperar adopcion.

Auditoria de Proyectos 2026-08-27.

Revision ID: 109
Revises: 108
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None

_COLUMNAS = [
    "retie_url", "tiene_almacenamiento", "capacidad_almacenamiento_kwh",
    "marca_almacenamiento", "modelo_almacenamiento",
]


def upgrade():
    bind = op.get_bind()
    for col in _COLUMNAS:
        if columna_existe(bind, "proyecto_info_tecnica", col):
            op.execute(f"ALTER TABLE proyecto_info_tecnica DROP COLUMN {col}")


def downgrade():
    # Deliberadamente vacio: las 5 columnas estaban vacias (0/110) -- recrearlas
    # no recupera ningun dato util.
    pass
