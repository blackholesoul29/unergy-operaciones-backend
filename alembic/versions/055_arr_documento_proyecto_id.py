"""Agrega proyecto_id a ArrDocumento (Despliegue 1 de eliminar ArrProyecto).

Revision ID: 055
Revises: 054
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arr_documento", sa.Column("proyecto_id", sa.BigInteger, sa.ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=True))


def downgrade() -> None:
    op.drop_column("arr_documento", "proyecto_id")
