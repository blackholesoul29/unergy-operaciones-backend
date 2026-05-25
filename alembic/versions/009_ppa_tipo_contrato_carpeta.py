"""add tipo_contrato and carpeta_link to ppa_contratos

Revision ID: 009
Revises: 008
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ppa_contratos", sa.Column("tipo_contrato", sa.String(20), nullable=True, server_default="venta"))
    op.add_column("ppa_contratos", sa.Column("carpeta_link", sa.String(1000), nullable=True))
    op.execute("UPDATE ppa_contratos SET tipo_contrato = 'venta' WHERE tipo_contrato IS NULL")


def downgrade() -> None:
    op.drop_column("ppa_contratos", "carpeta_link")
    op.drop_column("ppa_contratos", "tipo_contrato")
