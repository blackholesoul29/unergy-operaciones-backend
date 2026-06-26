"""add om_documento_proyecto table

Revision ID: 026
Revises: 5650ccf73b5c
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "5650ccf73b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "om_documento_proyecto",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("contrato_id", sa.BigInteger,
                  sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("nombre_archivo", sa.String(500), nullable=False),
        sa.Column("ruta_local", sa.String(1000), nullable=False),
        sa.Column("procesado_en", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("contrato_id", "periodo",
                            name="uq_om_doc_contrato_periodo"),
    )


def downgrade() -> None:
    op.drop_table("om_documento_proyecto")
