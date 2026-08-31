"""crear tabla contrato_factura, reemplazo de JSONB facturas_solenium/inversionistas

Auditoria de "JSON suelto" 2026-08-30: facturas_solenium/facturas_inversionistas
en contratos_servicio eran listas de dicts de forma fija -- tabla disfrazada
de JSON. Esta migracion solo CREA la tabla nueva; el DROP de las 2 columnas
JSONB viejas de contratos_servicio queda para una migracion aparte, una vez
confirmado (via scripts/migrar_facturas_a_contrato_factura.py) que los datos
ya se movieron.

Revision ID: 131
Revises: 130
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "131"
down_revision = "130"
branch_labels = None
depends_on = None


def upgrade():
    tipo_factura_enum = postgresql.ENUM("solenium", "inversionista", name="tipo_factura_enum")
    tipo_factura_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "contrato_factura",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("contrato_id", sa.BigInteger,
                  sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", tipo_factura_enum, nullable=False),
        sa.Column("fecha", sa.String(7), nullable=False),
        sa.Column("inversionista", sa.String(255), nullable=True),
        sa.Column("numero_factura", sa.String(100), nullable=True),
        sa.Column("monto", sa.Numeric(14, 2), nullable=True),
        sa.Column("enlace_soporte", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contrato_factura_contrato_id", "contrato_factura", ["contrato_id"])


def downgrade():
    op.drop_index("ix_contrato_factura_contrato_id", table_name="contrato_factura")
    op.drop_table("contrato_factura")
    postgresql.ENUM(name="tipo_factura_enum").drop(op.get_bind(), checkfirst=True)
