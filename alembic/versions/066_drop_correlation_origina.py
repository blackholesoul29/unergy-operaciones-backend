"""drop correlation_sync_log y columnas requestsdb_supply_id/quoia_node_name

Se retira toda la correlacion cross-DB con Origina (originabotdb) y
RequestsDB: la pestana "Datos Externos" y su boton "Sincronizar" (endpoint
/correlation/*), el job diario (2am COT), y app/services/correlation.py
completo. Motivo: ORIGINA_DATABASE_URL/REQUESTSDB_DATABASE_URL viven en
infraestructura de Origina (GCP, fuera de este proyecto), inalcanzable desde
Railway hace 8 dias corridos (connection timeout expired, ver
correlation_sync_log), y el rendimiento real de la funcion era minimo (15
origina_code + 6 requestsdb_supply_id en 194 proyectos vivos, el resto de
origina_code -87%- viene de Sun Factory via tsf_sync.py, que no depende de
esto y sigue intacto).

origina_code NO se toca aqui -- sigue vivo, lo llena tsf_sync.py.

Revision ID: 066
Revises: 065
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "requestsdb_supply_id")
    op.drop_column("proyectos", "quoia_node_name")
    op.drop_table("correlation_sync_log")


def downgrade():
    op.add_column("proyectos", sa.Column("requestsdb_supply_id", sa.BigInteger(), nullable=True))
    op.add_column("proyectos", sa.Column("quoia_node_name", sa.String(length=255), nullable=True))
    op.create_table(
        "correlation_sync_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("projects_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlations_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origina_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requestsdb_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_correlation_sync_at", "correlation_sync_log", ["synced_at"], postgresql_ops={"synced_at": "DESC"})
