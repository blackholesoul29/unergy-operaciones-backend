"""fronteras: eliminar codigo_propio -- sin conexion real

Auditoria de calidad de datos de Fronteras (2026-08-25): codigo_propio no
tiene FK ni es leido por ninguna logica de negocio -- solo se mostraba y
editaba en FronteraDetailView.vue. 94/145 filas vivas tenian valor (import
historico de GESCON, sin pipeline que lo siga poblando), y la muestra
("AGUSTIN GEN", "BARAYA AUX", "Chiriguana N2 Aux"...) es un alias legible
redundante con nombre_frontera, que ya cumple ese rol. Confirmado con Sara
antes de eliminar.

Revision ID: 087
Revises: 086
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("fronteras", "codigo_propio")


def downgrade():
    op.add_column("fronteras", sa.Column("codigo_propio", sa.String(length=100), nullable=True))
