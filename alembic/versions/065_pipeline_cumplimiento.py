"""Pipeline mensual de cumplimiento: origen/fecha_calculo + enlace XM.

Añade a ``cumplimiento_mensual`` el origen del cálculo ('manual' vs.
'automatico') y la marca de tiempo del último recálculo, y a
``liquidacion_xm_datos`` el enlace al snapshot de cumplimiento que generó cada
dato XM (para poder regenerarlos de forma idempotente y rastrear su origen).

Revision ID: 065
Revises: 059
Create Date: 2026-07-12
"""
from alembic import op

revision = "065"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cumplimiento_mensual ADD COLUMN IF NOT EXISTS "
        "origen VARCHAR NOT NULL DEFAULT 'manual'"
    )
    op.execute(
        "ALTER TABLE cumplimiento_mensual ADD COLUMN IF NOT EXISTS "
        "fecha_calculo TIMESTAMPTZ DEFAULT NOW()"
    )
    op.execute(
        "ALTER TABLE liquidacion_xm_datos ADD COLUMN IF NOT EXISTS "
        "cumplimiento_mensual_id BIGINT REFERENCES cumplimiento_mensual(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_liquidacion_xm_dato_cumplimiento_id "
        "ON liquidacion_xm_datos (cumplimiento_mensual_id) "
        "WHERE cumplimiento_mensual_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_liquidacion_xm_dato_cumplimiento_id")
    op.execute("ALTER TABLE liquidacion_xm_datos DROP COLUMN IF EXISTS cumplimiento_mensual_id")
    op.execute("ALTER TABLE cumplimiento_mensual DROP COLUMN IF EXISTS fecha_calculo")
    op.execute("ALTER TABLE cumplimiento_mensual DROP COLUMN IF EXISTS origen")
