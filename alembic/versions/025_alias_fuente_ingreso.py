"""Alias persistente de fuentes de ingreso (Panel Contable, Fase 2)

Nombre que la usuaria le pone a cada fuente de ingreso, anclado a la celda del ER
(columna_origen, ej. "Sheet1!G35"). Idempotente.

NOTA: el esquema de producción se provisiona vía _PENDING_DDLS en app/main.py.
Históricamente Alembic estaba roto (heads múltiples); la cadena se relinealizó
(nightwatch 2026-06-26), por lo que `alembic upgrade head` ya vuelve a resolver.

Revision ID: 025
Revises: 024b
Create Date: 2026-06-18
"""
from alembic import op

revision = "025"
down_revision = "024b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alias_fuente_ingreso (
            id            BIGSERIAL PRIMARY KEY,
            proyecto_id   BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            columna_origen VARCHAR(40) NOT NULL,
            etiqueta      VARCHAR(255) NOT NULL,
            orden         INTEGER NOT NULL DEFAULT 0,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_alias_proyecto_columna UNIQUE (proyecto_id, columna_origen)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_alias_proyecto ON alias_fuente_ingreso (proyecto_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alias_fuente_ingreso")
