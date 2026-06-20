"""add mantenimiento/arriendo/internet service types and pagos_servicio table

Revision ID: 011
Revises: 010
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend servicio_aplica_enum with new values
    op.execute("ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'mantenimiento'")
    op.execute("ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'arriendo'")
    op.execute("ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'internet'")

    # 2. New fields on contratos_servicio
    op.add_column("contratos_servicio", sa.Column("fecha_firma_contrato", sa.Date, nullable=True))
    op.add_column("contratos_servicio", sa.Column("enlace_drive", sa.String(1000), nullable=True))
    op.add_column("contratos_servicio", sa.Column("estado_pago", sa.String(20), nullable=True))

    # 3. New enum for payment status
    estado_pago_enum = sa.Enum("pendiente", "revisado", "aprobado", name="estado_pago_enum")
    estado_pago_enum.create(op.get_bind(), checkfirst=True)

    # 4. Create pagos_servicio table
    op.create_table(
        "pagos_servicio",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("contrato_id", sa.BigInteger,
                  sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mes", sa.Integer, nullable=False),
        sa.Column("año", sa.Integer, nullable=False),
        sa.Column("valor_pagado", sa.Numeric(14, 2), nullable=True),
        sa.Column("estado",
                  sa.Enum("pendiente", "revisado", "aprobado", name="estado_pago_enum"),
                  nullable=False, server_default="pendiente"),
        sa.Column("enlace_factura", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("mes >= 1 AND mes <= 12", name="ck_pago_servicio_mes_rango"),
        sa.CheckConstraint("año >= 2020 AND año <= 2099", name="ck_pago_servicio_ano_rango"),
        sa.UniqueConstraint("contrato_id", "mes", "año", name="uq_pago_servicio_contrato_periodo"),
    )
    op.create_index("ix_pagos_servicio_contrato_id", "pagos_servicio", ["contrato_id"])


def downgrade() -> None:
    op.drop_index("ix_pagos_servicio_contrato_id", table_name="pagos_servicio")
    op.drop_table("pagos_servicio")
    sa.Enum(name="estado_pago_enum").drop(op.get_bind(), checkfirst=True)
    op.drop_column("contratos_servicio", "estado_pago")
    op.drop_column("contratos_servicio", "enlace_drive")
    op.drop_column("contratos_servicio", "fecha_firma_contrato")
    # PostgreSQL does not support removing enum values — servicio_aplica_enum keeps the new values
