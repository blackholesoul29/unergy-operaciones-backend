"""Marca de auditoría para el lote mensual de borradores de liquidación.

`fecha_creacion_automatica` distingue las liquidaciones generadas por el job
mensual (LiquidacionBatchService) de las creadas a mano. El "borrador" en sí
reutiliza el estado existente `iniciada` y la unicidad ya la garantiza
`uq_liquidacion_proyecto_periodo` (proyecto_id, periodo), por lo que aquí solo
se añade la columna de auditoría.

Revision ID: 20260616
Revises: 039
Create Date: 2026-07-07
"""
from alembic import op

revision = "20260616"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE liquidaciones "
        "ADD COLUMN IF NOT EXISTS fecha_creacion_automatica TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE liquidaciones DROP COLUMN IF EXISTS fecha_creacion_automatica")
