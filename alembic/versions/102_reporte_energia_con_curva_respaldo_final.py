"""reporte_energia_consumo: agrega curva_respaldo_final + respaldo_final_origen

Extiende a Consumo el mismo mecanismo de "respaldo real vs estimado" que
ya tiene Generacion (ver migracion 099) -- pedido de Sara 2026-08-26: "la
misma logica de Generacion si se usa principal y respaldo tiene un dato
con 1.5 kWh por encima o por debajo que se use, sino que mantenga la
estimacion".

Idempotente por el mismo motivo que las migraciones recientes de esta
sesion: alembic upgrade head no siempre corre limpio en el deploy de
Railway.

Revision ID: 102
Revises: 101
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columnas = {c["name"] for c in inspector.get_columns("reporte_energia_consumo")}
    with op.batch_alter_table("reporte_energia_consumo") as batch_op:
        if "curva_respaldo_final" not in columnas:
            batch_op.add_column(sa.Column("curva_respaldo_final", sa.dialects.postgresql.JSONB(), nullable=True))
        if "respaldo_final_origen" not in columnas:
            batch_op.add_column(sa.Column("respaldo_final_origen", sa.String(20), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columnas = {c["name"] for c in inspector.get_columns("reporte_energia_consumo")}
    with op.batch_alter_table("reporte_energia_consumo") as batch_op:
        if "respaldo_final_origen" in columnas:
            batch_op.drop_column("respaldo_final_origen")
        if "curva_respaldo_final" in columnas:
            batch_op.drop_column("curva_respaldo_final")
