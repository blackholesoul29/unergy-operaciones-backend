"""add es_duplicado flag to asic_solicitudes

When a plant appears in multiple contracts, the user marks extra
assignments as 'duplicado'.  A duplicado means Unergy treats that
contract share as spot-market (bolsa) exposure at the plant's
dispatch percentage, not as actual generation.

Revision ID: 010
Revises: 009
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asic_solicitudes",
        sa.Column("es_duplicado", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("asic_solicitudes", "es_duplicado")
