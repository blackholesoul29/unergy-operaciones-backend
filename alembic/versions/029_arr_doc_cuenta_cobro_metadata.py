"""Add cuenta de cobro metadata columns to arr_documento (matching por predio).

Revision ID: 029
Revises: 028
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: create_all (init_db) puede haber agregado ya estas columnas.
    table = "arr_documento"
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(table)}
    cols = [
        sa.Column("codigo_predio",       sa.String(120),    nullable=True),
        sa.Column("numero_cuenta_cobro", sa.String(60),     nullable=True),
        sa.Column("nombre_arrendatario", sa.String(255),    nullable=True),
        sa.Column("valor_individual",    sa.Numeric(15, 2), nullable=True),
    ]
    for col in cols:
        if col.name not in existing:
            op.add_column(table, col)


def downgrade() -> None:
    op.drop_column("arr_documento", "valor_individual")
    op.drop_column("arr_documento", "nombre_arrendatario")
    op.drop_column("arr_documento", "numero_cuenta_cobro")
    op.drop_column("arr_documento", "codigo_predio")
