"""Agrega plan_datos_gb, velocidad_mbps, tipo_conexion a ContratoServicio.

Revision ID: 057
Revises: 056
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contratos_servicio", sa.Column("plan_datos_gb", sa.String(50), nullable=True))
    op.add_column("contratos_servicio", sa.Column("velocidad_mbps", sa.Integer, nullable=True))
    op.add_column("contratos_servicio", sa.Column("tipo_conexion", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("contratos_servicio", "tipo_conexion")
    op.drop_column("contratos_servicio", "velocidad_mbps")
    op.drop_column("contratos_servicio", "plan_datos_gb")
