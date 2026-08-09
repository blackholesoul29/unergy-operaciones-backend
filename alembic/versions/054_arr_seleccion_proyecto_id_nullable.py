"""Permite arr_proyecto_id NULL en arr_seleccion_mensual: calcular_periodo ahora
genera una fila por arrendador, y puede no existir un ArrProyecto real detrás.

Revision ID: 054
Revises: 053
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("arr_seleccion_mensual", "arr_proyecto_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("arr_seleccion_mensual", "arr_proyecto_id", existing_type=sa.BigInteger(), nullable=False)
