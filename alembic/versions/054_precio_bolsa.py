"""Tabla precio_bolsa (módulo Riesgos de Bolsa)

Revision ID: 054
Revises: 053
Create Date: 2026-07-06

Relinealizada de 036→037 (nightwatch): el build original forkeó de master (head
035) y reclamó "036", colisionando con 036_contrato_servicio_detail_fields.py
(otra rama pendiente que también forkeó de 035). Dos revisiones "036" rompen
`alembic upgrade head` al mergear la segunda. Aquí encadena tras contratos (036).
"""
from alembic import op

revision = "054"
down_revision = "053"
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
