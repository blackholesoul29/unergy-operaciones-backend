"""Crea liquidacion_xm_dato: datos crudos de liquidación XM ingeridos por archivo.

Tabla del pipeline de ingesta de archivos XM (`listado_recursos.xlsx`,
`generacion_distribuida.xlsx`). NO confundir con `liquidacion_xm_datos` (detalle
de facturación por frontera): esta es `liquidacion_xm_dato` (singular) y almacena
las filas crudas por recurso/fecha con hash de integridad para deduplicar.

Revision ID: 050
Revises: 046
Create Date: 2026-07-11
"""
from alembic import op

revision = "050"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS liquidacion_xm_dato (
            id BIGSERIAL PRIMARY KEY,
            codigo_recurso VARCHAR(50) NOT NULL,
            fecha DATE NOT NULL,
            agente VARCHAR(100),
            tipo_recurso VARCHAR(100),
            capacidad_efectiva_neta_mw NUMERIC(10, 4),
            generacion_kwh NUMERIC(18, 4),
            precio_liquidacion_cop_kwh NUMERIC(18, 4),
            valor_liquidacion_cop NUMERIC(18, 2),
            fuente_archivo VARCHAR(100) NOT NULL,
            fecha_ingesta TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            hash_fila VARCHAR(64) NOT NULL
        )"""
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_liquidacion_xm_dato_hash "
        "ON liquidacion_xm_dato (hash_fila)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_liquidacion_xm_dato_recurso_fecha "
        "ON liquidacion_xm_dato (codigo_recurso, fecha)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_liquidacion_xm_dato_recurso_fecha")
    op.execute("DROP INDEX IF EXISTS uq_liquidacion_xm_dato_hash")
    op.execute("DROP TABLE IF EXISTS liquidacion_xm_dato")
