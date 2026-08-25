"""drop proyectos.estado_resultados_url/income_distribution_method/generar_liquidacion

Los 3 confirmados sin uso real (verificado con agente + grep directo,
2026-08-20): cero UI en el frontend, cero escritor especifico, cero
lector con logica real -- solo aparecian en el modelo y en los schemas.

Cuidado: `estado_resultados_url` tambien existe en `Liquidacion`
(app/models/liquidaciones.py), que es un campo COMPLETAMENTE DISTINTO y
real (lo llena app/utils/liquidaciones_loader.py, tiene UI en
LiquidacionDetailView.vue) -- esta migracion NO lo toca, solo dropea la
columna de `proyectos`.

Revision ID: 069
Revises: 068
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "estado_resultados_url")
    op.drop_column("proyectos", "income_distribution_method")
    op.drop_column("proyectos", "generar_liquidacion")


def downgrade():
    op.add_column("proyectos", sa.Column("estado_resultados_url", sa.String(length=1000), nullable=True))
    op.add_column("proyectos", sa.Column("income_distribution_method", sa.String(length=100), nullable=True))
    op.add_column("proyectos", sa.Column("generar_liquidacion", sa.Boolean(), nullable=False, server_default=sa.text("false")))
