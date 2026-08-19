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
from alembic_idempotencia import columna_existe

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Fix 2026-08-19: si _PENDING_DDLS ya corrió (crea 'gen_promedio_dias'
    # directamente, con ese nombre final) antes de que esta migración
    # pudiera renombrar 'gen_promedio_meses', las dos columnas coexisten --
    # renombrar tronaría con DuplicateColumn. Ninguna se llegó a poblar
    # (ver docstring del módulo), así que no hay dato que reconciliar: si el
    # destino ya existe, no hay nada que hacer.
    if columna_existe(bind, "proyectos", "gen_promedio_dias"):
        return
    if columna_existe(bind, "proyectos", "gen_promedio_meses"):
        op.alter_column("proyectos", "gen_promedio_meses", new_column_name="gen_promedio_dias")


def downgrade() -> None:
    op.alter_column("proyectos", "gen_promedio_dias", new_column_name="gen_promedio_meses")
