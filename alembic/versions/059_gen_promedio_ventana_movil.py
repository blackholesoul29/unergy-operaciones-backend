"""El promedio de generación pasa a una ventana móvil de 30 días.

Antes se promediaban los últimos N meses CALENDARIO completos. Un promedio "de
julio" consultado el 9 de agosto describe algo que terminó hace más de una
semana; una ventana móvil de 30 días describe la planta hoy.

Por eso `gen_promedio_meses` (cuántos meses entraron) deja de tener sentido y
pasa a ser `gen_promedio_dias` (cuántos días CON LECTURA entraron, de los 30).

Es un rename, no un borrado: la columna se agregó en la 058 y nunca se llegó a
poblar, así que no hay dato que migrar.

Revision ID: 059
Revises: 058
Create Date: 2026-08-09
"""
from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("proyectos", "gen_promedio_meses", new_column_name="gen_promedio_dias")


def downgrade() -> None:
    op.alter_column("proyectos", "gen_promedio_dias", new_column_name="gen_promedio_meses")
