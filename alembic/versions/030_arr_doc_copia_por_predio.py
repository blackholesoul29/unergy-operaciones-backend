"""arr_documento: una copia por predio (arr_proyecto_id nullable + ruta_original).

Revision ID: 030
Revises: 029
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: create_all (init_db) ya refleja el modelo final (ruta_original
    # presente y arr_proyecto_id nullable), así que sólo aplicamos lo que falte.
    table = "arr_documento"
    insp = sa.inspect(op.get_bind())
    cols = {c["name"]: c for c in insp.get_columns(table)}

    if "ruta_original" not in cols:
        op.add_column(table, sa.Column("ruta_original", sa.String(1000), nullable=True))

    # Sólo aflojar el NOT NULL si todavía es NOT NULL. batch_alter_table funciona
    # tanto en Postgres (emite ALTER COLUMN) como en SQLite (recrea la tabla).
    if "arr_proyecto_id" in cols and not cols["arr_proyecto_id"]["nullable"]:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("arr_proyecto_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("arr_documento", "arr_proyecto_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("arr_documento", "ruta_original")
