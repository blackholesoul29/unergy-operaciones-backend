"""proyectos.reportar_asic_forzado -- eliminar (superada por Quoia como fuente de verdad)

Decidido con el usuario (Sara) 2026-08-21: en vez de mantener una lista
propia de excepciones al filtro del clasificador
(orquestador._fronteras_con_reporte), se compararon en vivo las fronteras
que hoy procesa el clasificador contra el listado real de borders
registrados en Quoia (gaia.get_all_borders(), lo mismo que alimenta la
vista "Reportes" de Quoia Manager). Resultado: 0 fronteras se habrían
perdido, y la regla propia (Proyecto.estado==en_operacion AND srv_cgm, con
esta bandera como excepción manual) ya tenía huecos reales -- GD Piojó y
GD La Hormiguita estaban registradas en Quoia pero nunca se marcaron a
mano con reportar_asic_forzado.

Se reemplaza el filtro por "codigo_frontera está en Quoia" directamente
(ver orquestador._fronteras_con_reporte) -- esta bandera queda redundante.

Revision ID: 074
Revises: 073
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "reportar_asic_forzado")


def downgrade():
    op.add_column(
        "proyectos",
        sa.Column("reportar_asic_forzado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
