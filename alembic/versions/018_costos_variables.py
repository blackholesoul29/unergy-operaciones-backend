"""Crear tabla costos_variables

Revision ID: 018
Revises: 017
Create Date: 2026-06-10
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS costos_variables (
            id                        BIGSERIAL PRIMARY KEY,
            proyecto_id               BIGINT NOT NULL REFERENCES proyectos(id),
            tipo_accion               VARCHAR(50) NOT NULL,
            tipo_equipo               VARCHAR(100) NOT NULL,
            monto                     NUMERIC(18,2) NOT NULL,
            fecha                     DATE NOT NULL,
            descripcion               TEXT NOT NULL,
            observaciones             TEXT,
            url_factura               VARCHAR(500),
            nombre_factura            VARCHAR(255),
            url_cotizacion            VARCHAR(500),
            nombre_cotizacion         VARCHAR(255),
            url_rut                   VARCHAR(500),
            nombre_rut                VARCHAR(255),
            url_certificado_bancario  VARCHAR(500),
            nombre_certificado_bancario VARCHAR(255),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at                TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_costos_variables_proyecto_id ON costos_variables(proyecto_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_costos_variables_fecha ON costos_variables(fecha)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS costos_variables")
