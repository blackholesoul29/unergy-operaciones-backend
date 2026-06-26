"""Add factura metadata columns to om_documento_proyecto.

Revision ID: 027
Revises: 026
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: create_all (init_db) puede haber agregado ya estas columnas.
    table = "om_documento_proyecto"
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(table)}
    cols = [
        sa.Column("numero_factura",      sa.String(30),      nullable=True),
        sa.Column("total_sin_impuestos", sa.Numeric(15, 2),  nullable=True),
        sa.Column("iva",                 sa.Numeric(15, 2),  nullable=True),
        sa.Column("total_pagar",         sa.Numeric(15, 2),  nullable=True),
        sa.Column("fecha_facturacion",   sa.Date(),          nullable=True),
        sa.Column("cufe",                sa.String(200),     nullable=True),
    ]
    for col in cols:
        if col.name not in existing:
            op.add_column(table, col)


def downgrade() -> None:
    op.drop_column("om_documento_proyecto", "cufe")
    op.drop_column("om_documento_proyecto", "fecha_facturacion")
    op.drop_column("om_documento_proyecto", "total_pagar")
    op.drop_column("om_documento_proyecto", "iva")
    op.drop_column("om_documento_proyecto", "total_sin_impuestos")
    op.drop_column("om_documento_proyecto", "numero_factura")
