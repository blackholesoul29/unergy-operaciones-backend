"""Agrega responsable_iva a contratos_servicio.

Provisionado también en main.py::_PENDING_DDLS (camino de deploy real del repo).

Revision ID: 051
Revises: 050
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contratos_servicio",
        sa.Column("responsable_iva", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("contratos_servicio", "responsable_iva")
