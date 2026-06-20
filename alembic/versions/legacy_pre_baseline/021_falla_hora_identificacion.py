"""Add hora_identificacion column to fallas

El modelo ya declaraba `hora_identificacion` pero nunca se creó la columna
vía migración. Esta migración la añade de forma idempotente para poder
registrar la hora exacta de identificación de la falla y calcular el tiempo
de afectación (fecha/hora solución − fecha/hora ocurrencia).

Revision ID: 021
Revises: 020
Create Date: 2026-06-16
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE fallas ADD COLUMN IF NOT EXISTS hora_identificacion TIME")


def downgrade() -> None:
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS hora_identificacion")
