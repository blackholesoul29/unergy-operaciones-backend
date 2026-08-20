"""drop proyectos.codigo_sic_generacion/codigo_sic_consumo (0 filas, sin UI)

Estas dos columnas nunca las llena ningun camino: no hay formulario en el
frontend, ningun script/job las escribe, y en produccion 0 de 194
proyectos vivos tienen dato. app/services/comercial.py las leia para el
arbol de /comercial/proyectos-operando, pero siempre devolvia null -- se
quita esa lectura en el mismo commit.

Los codigos SIC reales que usa el ciclo de liquidaciones (sic_gen/sic_con)
viven en la API externa de Liquidaciones, no en esta base -- ver
app/services/liquidaciones_api.py, docstring: "Los datos maestros que usa
el ciclo de liquidaciones ... viven en esa API y no en esta base de
datos." Son dos almacenamientos independientes que nunca se cruzaron;
estas columnas eran el intento original antes de esa integracion, y
quedaron huerfanas.

Revision ID: 068
Revises: 067
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "codigo_sic_generacion")
    op.drop_column("proyectos", "codigo_sic_consumo")


def downgrade():
    op.add_column("proyectos", sa.Column("codigo_sic_generacion", sa.String(length=50), nullable=True))
    op.add_column("proyectos", sa.Column("codigo_sic_consumo", sa.String(length=50), nullable=True))
