"""Motor de liquidación XM: tabla intermedia de cálculo por proyecto/período.

Guarda el resultado del motor de liquidación automática que cruza la
generación real de una planta con su compromiso PPA y el precio promedio de
bolsa (XM) del mes, para calcular la diferencia energética y su valoración
monetaria (liquidación).

NOTA de diseño: la especificación original pedía nombrar esta tabla
`liquidacion_xm_datos`, pero ese nombre YA existe con un esquema distinto
(detalle de facturación por frontera vinculado a `liquidaciones`, ver
`app/models/liquidaciones.py::LiquidacionXMDato`). Para no romper esa tabla se
usa el nombre `liquidacion_xm_calculos`, que refleja mejor su propósito: el
CÁLCULO del motor de liquidación (gen real vs compromiso a precio XM).

Revision ID: 049
Revises: 046
Create Date: 2026-07-11
"""
from alembic import op

revision = "049"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS liquidacion_xm_calculos (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            periodo DATE NOT NULL,
            generacion_real NUMERIC(15, 4) NOT NULL,
            compromiso_ppa NUMERIC(15, 4) NOT NULL,
            precio_xm_promedio NUMERIC(15, 4) NOT NULL,
            diferencia_mwh NUMERIC(15, 4) NOT NULL,
            valor_liquidacion NUMERIC(15, 2) NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_liquidacion_xm_calc_proyecto_periodo UNIQUE (proyecto_id, periodo)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_liquidacion_xm_calc_proyecto_periodo "
        "ON liquidacion_xm_calculos (proyecto_id, periodo)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_liquidacion_xm_calc_proyecto_periodo")
    op.execute("DROP TABLE IF EXISTS liquidacion_xm_calculos")
