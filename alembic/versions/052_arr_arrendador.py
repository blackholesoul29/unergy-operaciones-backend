"""Agrega tabla arr_arrendador (varios arrendadores por contrato de arriendo).

Revision ID: 052
Revises: 051
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from alembic_idempotencia import crear_tabla_si_falta

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    crear_tabla_si_falta(
        bind, "arr_arrendador",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("contrato_id", sa.BigInteger, sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("valor_base", sa.Numeric(14, 2), nullable=True),
        sa.Column("responsable_iva", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        migracion="052",
    )


def downgrade() -> None:
    op.drop_table("arr_arrendador")
