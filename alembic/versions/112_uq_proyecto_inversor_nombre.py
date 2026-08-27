"""proyecto_inversores: UNIQUE(proyecto_id, nombre)

Protege contra la condicion de carrera de backfill_inversores_minigranjas():
dos llamadas cercanas (doble clic del boton "Inversores minigranja", o dos
requests casi simultaneas) podian ver "0 inversores" antes de que la
primera confirmara, y ambas sembraban el set completo de 5 inversores
tipicos -- duplicado en silencio.

Confirmado en produccion 2026-08-27: 6 proyectos con hasta 3 copias
identicas (peor caso: MGS 0032 El Paso Norte, 15 filas en vez de 5, sumando
2.970 kW contra una potencia AC real de 990 kW). Las 40 filas duplicadas
(mismo proyecto_id + nombre) se limpiaron a mano antes de esta migracion,
conservando la de menor id de cada grupo -- son copias exactas sin ningun
dato distinto que perder (marca/modelo/numero_serie vacios en las 715
filas, son puramente sinteticas del backfill).

Revision ID: 112
Revises: 111
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import constraint_existe

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not constraint_existe(bind, "proyecto_inversores", "uq_proyecto_inversor_nombre"):
        op.create_unique_constraint(
            "uq_proyecto_inversor_nombre", "proyecto_inversores", ["proyecto_id", "nombre"],
        )


def downgrade():
    op.drop_constraint("uq_proyecto_inversor_nombre", "proyecto_inversores", type_="unique")
