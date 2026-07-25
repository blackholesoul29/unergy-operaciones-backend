"""Penalidad contractual del PPA para valorar el déficit de cumplimiento.

El impacto del déficit se estimaba siempre a precio de bolsa. Muchos PPA pactan
una penalidad por MWh no entregado que puede superar la bolsa; valorar a bolsa
subestimaba el golpe. `tipo_precio_referencia` decide qué precio manda.

`precio_penalidad_mwh` va en COP/MWh (el precio de bolsa se guarda en COP/kWh:
la conversión vive en app/services/cumplimiento_service.py).

Guardas de existencia: estas columnas también las crea el DDL de arranque de
main.py, que es el camino real de deploy — la migración tiene que ser idempotente.

Revision ID: 055
Revises: 047
Create Date: 2026-07-14
"""
from alembic import op

revision = "055"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS "
        "precio_penalidad_mwh NUMERIC(12,2)"
    )
    op.execute(
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS "
        "tipo_precio_referencia VARCHAR(50) NOT NULL DEFAULT 'HIBRIDO'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ppa_contratos DROP COLUMN IF EXISTS tipo_precio_referencia")
    op.execute("ALTER TABLE ppa_contratos DROP COLUMN IF EXISTS precio_penalidad_mwh")
