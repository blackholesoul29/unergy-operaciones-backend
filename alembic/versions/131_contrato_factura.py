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

from alembic_idempotencia import crear_tabla_si_falta

revision = "131"
down_revision = "130"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # create_type=False es obligatorio: sin eso, op.create_table vuelve a emitir
    # CREATE TYPE al construir la columna `tipo` (sin checkfirst) y revienta con
    # DuplicateObject si el enum ya existe -- que es lo normal aca, porque
    # `create_all()` corre ANTES que Alembic en cada arranque y ya lo creo.
    tipo_factura_enum = postgresql.ENUM(
        "solenium", "inversionista", name="tipo_factura_enum", create_type=False)
    postgresql.ENUM(
        "solenium", "inversionista", name="tipo_factura_enum"
    ).create(bind, checkfirst=True)

    crear_tabla_si_falta(
        bind,
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
        migracion="131",
    )
    # IF NOT EXISTS y no op.create_index: si la tabla ya existia, el indice
    # tambien puede existir (lo declara el modelo, asi que lo crea create_all).
    op.execute("CREATE INDEX IF NOT EXISTS ix_contrato_factura_contrato_id "
               "ON contrato_factura (contrato_id)")


def downgrade():
    op.drop_index("ix_contrato_factura_contrato_id", table_name="contrato_factura")
    op.drop_table("contrato_factura")
    postgresql.ENUM(name="tipo_factura_enum").drop(op.get_bind(), checkfirst=True)
