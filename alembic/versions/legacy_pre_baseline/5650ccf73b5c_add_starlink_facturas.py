"""add_starlink_facturas

Revision ID: 5650ccf73b5c
Revises: 019
Create Date: 2026-06-10 22:51:56.085021

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "5650ccf73b5c"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "starlink_facturas",
        sa.Column("id",             sa.BigInteger(),    nullable=False),
        sa.Column("periodo",        sa.String(7),       nullable=False),
        sa.Column("items_json",     sa.Text(),          nullable=False),
        sa.Column("agrupado_json",  sa.Text(),          nullable=False),
        sa.Column("cargos_totales", sa.Numeric(15, 2),  nullable=True),
        sa.Column("suma_items",     sa.Numeric(15, 2),  nullable=False),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("periodo"),
    )
    op.create_index("ix_starlink_facturas_periodo", "starlink_facturas", ["periodo"])


def downgrade() -> None:
    op.drop_index("ix_starlink_facturas_periodo", table_name="starlink_facturas")
    op.drop_table("starlink_facturas")
