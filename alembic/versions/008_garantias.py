"""add garantias and garantias_movimientos tables

Revision ID: 008
Revises: 007
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    tipo_garantia = sa.Enum(
        "cuenta_custodia", "poliza", "carta_credito", "fiducia", "otro",
        name="tipogarantiaenum",
    )
    estado_garantia = sa.Enum(
        "vigente", "vencida", "en_renovacion", "liberada", "en_proceso",
        name="estadogarantiaenum",
    )
    tipo_movimiento = sa.Enum(
        "deposito", "cobro_xm", "devolucion", "ajuste", "interes", "renovacion",
        name="tipomovimientoenum",
    )

    op.create_table(
        "garantias",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("proyecto_id", sa.BigInteger, sa.ForeignKey("proyectos.id"), nullable=True, index=True),
        sa.Column("contrato_ppa_id", sa.BigInteger, sa.ForeignKey("ppa_contratos.id"), nullable=True, index=True),
        sa.Column("codigo_frontera", sa.String(50), nullable=True),
        sa.Column("tipo", tipo_garantia, nullable=False),
        sa.Column("entidad", sa.String(200), nullable=True),
        sa.Column("numero_referencia", sa.String(100), nullable=True),
        sa.Column("valor_cop", sa.Numeric(18, 2), nullable=False),
        sa.Column("porcentaje_cobertura", sa.Numeric(5, 2), nullable=True),
        sa.Column("fecha_constitucion", sa.Date, nullable=True),
        sa.Column("fecha_vencimiento", sa.Date, nullable=True),
        sa.Column("estado", estado_garantia, nullable=False, server_default="vigente"),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "garantias_movimientos",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("garantia_id", sa.BigInteger, sa.ForeignKey("garantias.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tipo", tipo_movimiento, nullable=False),
        sa.Column("monto_cop", sa.Numeric(18, 2), nullable=False),
        sa.Column("saldo_posterior_cop", sa.Numeric(18, 2), nullable=True),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("concepto", sa.Text, nullable=True),
        sa.Column("referencia_xm", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_garantias_estado_vencimiento", "garantias", ["estado", "fecha_vencimiento"])
    op.create_index("ix_garantias_movimientos_fecha", "garantias_movimientos", ["garantia_id", "fecha"])


def downgrade() -> None:
    op.drop_table("garantias_movimientos")
    op.drop_table("garantias")
    op.execute("DROP TYPE IF EXISTS tipomovimientoenum")
    op.execute("DROP TYPE IF EXISTS estadogarantiaenum")
    op.execute("DROP TYPE IF EXISTS tipogarantiaenum")
