"""proyectos.gen_promedio_meses -- eliminar columna huerfana

La migracion 059 (gen_promedio_ventana_movil) queria renombrar
gen_promedio_meses -> gen_promedio_dias, pero el fallback pre-Alembic de
_PENDING_DDLS (app/main.py) ya habia creado gen_promedio_dias por su cuenta
antes de que esa migracion corriera -- su propio guard
(if columna_existe(..., "gen_promedio_dias"): return) hizo que la migracion
se saltara el DROP de la columna vieja. Resultado: gen_promedio_meses quedo
viva en produccion junto a gen_promedio_dias desde entonces, sin campo en el
modelo y sin ningun lector -- 0/194 proyectos poblados.

Hallazgo #5 de la auditoria de Proyectos 2026-08-27.

Revision ID: 104
Revises: 103
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "gen_promedio_meses"):
        op.execute("ALTER TABLE proyectos DROP COLUMN gen_promedio_meses")


def downgrade():
    # Deliberadamente vacio: la columna esta vacia y sin modelo desde antes
    # de esta migracion -- recrearla no recupera ningun dato.
    pass
