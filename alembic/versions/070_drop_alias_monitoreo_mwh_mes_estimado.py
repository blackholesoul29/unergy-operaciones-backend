"""drop proyectos.alias_monitoreo y proyectos.mwh_mes_estimado (0/194 uso real)

Decidido con el usuario (Sara) 2026-08-20, tras revisar en detalle que ambos
son "feature sin adoptar": codigo real (fallbacks conectados en 8+ archivos
para alias_monitoreo; cadena de estimacion de generacion para
mwh_mes_estimado), pero SIN NINGUN camino de entrada desde el frontend --
alias_monitoreo ni siquiera estaba expuesto en los schemas Pydantic, y
mwh_mes_estimado solo se mostraba de forma read-only en dos vistas
(Proximos a energizar, Oportunidad). 0/194 proyectos con dato en ninguno
de los dos, siempre.

Todos los fallbacks `sub_project or alias_monitoreo` se simplificaron a
`sub_project` (comportamiento identico hoy, ya que alias_monitoreo siempre
fue None). La cadena de generacion estimada de comercial.py salta
directo de "medido" a "promedio de p50" (mwh_mes_estimado tampoco aportaba
nada en la practica).

proyecto_padre_id se mantiene a proposito -- a diferencia de estos dos,
tiene un escritor real y activo (merge_proyectos, la misma herramienta
usada hoy para fusionar Astrea 1/2).

Revision ID: 070
Revises: 069
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "alias_monitoreo")
    op.drop_column("proyectos", "mwh_mes_estimado")


def downgrade():
    op.add_column("proyectos", sa.Column("alias_monitoreo", sa.Text(), nullable=True))
    op.add_column("proyectos", sa.Column("mwh_mes_estimado", sa.Numeric(12, 2), nullable=True))
