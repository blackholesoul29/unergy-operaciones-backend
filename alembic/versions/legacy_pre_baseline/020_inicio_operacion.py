"""Crear tabla proyecto_inicio_operacion

Revision ID: 020
Revises: 5650ccf73b5c
Create Date: 2026-06-11
"""
from alembic import op

revision = "020"
down_revision = "5650ccf73b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS proyecto_inicio_operacion (
            id                      BIGSERIAL PRIMARY KEY,
            proyecto_id             BIGINT NOT NULL UNIQUE REFERENCES proyectos(id),
            empresa_contratista     VARCHAR(255),
            fecha_energizacion      DATE,
            fecha_inicio_operacion  DATE,
            checklist               JSONB NOT NULL DEFAULT '{}'::jsonb,
            pruebas                 JSONB NOT NULL DEFAULT '{}'::jsonb,
            documentos              JSONB NOT NULL DEFAULT '{}'::jsonb,
            pendientes              JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyecto_inicio_operacion_proyecto_id "
        "ON proyecto_inicio_operacion(proyecto_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proyecto_inicio_operacion")
