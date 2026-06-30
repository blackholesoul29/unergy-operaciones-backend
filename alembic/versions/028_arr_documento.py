"""Add arr_documento table for arriendos payment documents.

Revision ID: 028
Revises: 027
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arr_documento",
        sa.Column("id",                sa.BigInteger(),  nullable=False),
        sa.Column("arr_proyecto_id",   sa.BigInteger(),  nullable=False),
        sa.Column("periodo",           sa.String(7),     nullable=False),
        sa.Column("pago_id",           sa.Integer(),     nullable=False),
        sa.Column("codigo_contrato",   sa.String(120),   nullable=False),
        sa.Column("tipo_documento",    sa.String(30),    nullable=False),
        sa.Column("nombre_archivo",    sa.String(500),   nullable=False),
        sa.Column("ruta_local",        sa.String(1000),  nullable=False),
        sa.Column("nombre_secundario", sa.String(500),   nullable=True),
        sa.Column("ruta_secundario",   sa.String(1000),  nullable=True),
        sa.Column("fecha_subida",      sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["arr_proyecto_id"], ["arr_proyectos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("arr_proyecto_id", "periodo", "pago_id", name="uq_arr_doc_proyecto_periodo_pago"),
    )
    op.create_index("ix_arr_documento_periodo",         "arr_documento", ["periodo"])
    op.create_index("ix_arr_documento_arr_proyecto_id", "arr_documento", ["arr_proyecto_id"])


def downgrade() -> None:
    op.drop_index("ix_arr_documento_arr_proyecto_id", table_name="arr_documento")
    op.drop_index("ix_arr_documento_periodo",         table_name="arr_documento")
    op.drop_table("arr_documento")
