"""cumplimiento_cierre_log: bitácora del cierre mensual automático de cumplimiento PPA

Espeja el DDL idempotente de `_PENDING_DDLS` en app/main.py, que es el que
realmente crea la tabla en el arranque. Por eso el CREATE lleva IF NOT EXISTS:
la migración debe ser un no-op cuando el arranque ya la creó.

Revision ID: 054
Revises: 047
"""
from alembic import op

revision = "054"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS cumplimiento_cierre_log (
            id BIGSERIAL PRIMARY KEY,
            ejecutado_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            origen VARCHAR(20) NOT NULL DEFAULT 'scheduler',
            contratos_procesados INTEGER NOT NULL DEFAULT 0,
            contratos_con_deficit INTEGER NOT NULL DEFAULT 0,
            contratos_cumplidos INTEGER NOT NULL DEFAULT 0,
            error TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cumplimiento_cierre_at "
        "ON cumplimiento_cierre_log (ejecutado_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cumplimiento_cierre_at")
    op.execute("DROP TABLE IF EXISTS cumplimiento_cierre_log")
