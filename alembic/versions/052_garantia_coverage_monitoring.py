"""Monitoreo de cobertura de garantías.

Agrega la configuración de monitoreo a `garantias` y crea la tabla histórica
`garantia_cobertura_historico` que registra cada verificación del job
`verificar_cobertura_de_garantias`.

Revision ID: 052
Revises: 047
Create Date: 2026-07-12
"""
from alembic import op

revision = "052"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS "
        "monitoreo_cobertura_activo BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS "
        "tipo_calculo_cobertura VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS "
        "umbral_alerta_amarilla NUMERIC(5,4) NOT NULL DEFAULT 0.95"
    )
    op.execute(
        "ALTER TABLE garantias ADD COLUMN IF NOT EXISTS "
        "umbral_alerta_roja NUMERIC(5,4) NOT NULL DEFAULT 0.90"
    )
    op.execute(
        """CREATE TABLE IF NOT EXISTS garantia_cobertura_historico (
            id BIGSERIAL PRIMARY KEY,
            garantia_id BIGINT NOT NULL REFERENCES garantias(id) ON DELETE CASCADE,
            fecha_verificacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            valor_requerido NUMERIC(20,2) NOT NULL,
            valor_actual_garantia NUMERIC(20,2) NOT NULL,
            cobertura_porcentaje NUMERIC(12,4),
            nivel_alerta VARCHAR(20) NOT NULL,
            detalles_calculo JSONB
        )"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_garantia_cobertura_historico_garantia_id "
        "ON garantia_cobertura_historico (garantia_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_garantia_cobertura_historico_fecha "
        "ON garantia_cobertura_historico (fecha_verificacion DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS garantia_cobertura_historico")
    op.execute("ALTER TABLE garantias DROP COLUMN IF EXISTS umbral_alerta_roja")
    op.execute("ALTER TABLE garantias DROP COLUMN IF EXISTS umbral_alerta_amarilla")
    op.execute("ALTER TABLE garantias DROP COLUMN IF EXISTS tipo_calculo_cobertura")
    op.execute("ALTER TABLE garantias DROP COLUMN IF EXISTS monitoreo_cobertura_activo")
