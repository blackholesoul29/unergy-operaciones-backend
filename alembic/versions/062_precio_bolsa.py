"""Tabla precio_bolsa (módulo Riesgos de Bolsa)

Revision ID: 062
Revises: 061
Create Date: 2026-07-06

Relinealizada dos veces: el build original forkeó de master (head 035) y
reclamó "036", colisionando con la migración de contratos-servicio (otra rama
que también forkeó de 035) — dos revisiones con el mismo id rompen
`alembic upgrade head` al mergear la segunda. Tras el avance de master a
049/050 (07-24) la cola completa se re-encadenó: esta quedó como 054 y cuelga
de 053 (contrato_servicio_detail_fields, en esta misma rama).
"""
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS precio_bolsa (
            id BIGSERIAL PRIMARY KEY,
            fecha_hora TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            precio_cop_mwh NUMERIC(10, 2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_precio_bolsa_fecha_hora "
        "ON precio_bolsa (fecha_hora)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS precio_bolsa")
