"""liquidaciones: nuevos tipos ingreso/costo, inversionista_id, soporte_url

Revision ID: 003
Revises: 002
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Nuevos valores en tipo_linea_mandato_enum ---
    op.execute("ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'despacho'")
    op.execute("ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'ventas_en_bolsa'")
    op.execute("ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'compras_en_bolsa'")
    op.execute("ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'redistribucion_ingresos'")
    op.execute("ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'")

    # --- Nuevo valor en tipo_costo_enum ---
    op.execute("ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'")

    # --- liquidacion_mandatos: FK a inversionista ---
    op.add_column('liquidacion_mandatos',
        sa.Column('inversionista_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_liq_mandato_inversionista',
        'liquidacion_mandatos', 'proyecto_inversionistas',
        ['inversionista_id'], ['id'],
        ondelete='SET NULL',
    )

    # --- liquidacion_costos: soporte_url ---
    op.add_column('liquidacion_costos',
        sa.Column('soporte_url', sa.String(1000), nullable=True))

    # --- liquidacion_facturas: nro_soporte + soporte_url ---
    op.add_column('liquidacion_facturas',
        sa.Column('nro_soporte', sa.String(100), nullable=True))
    op.add_column('liquidacion_facturas',
        sa.Column('soporte_url', sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column('liquidacion_facturas', 'soporte_url')
    op.drop_column('liquidacion_facturas', 'nro_soporte')
    op.drop_column('liquidacion_costos', 'soporte_url')
    op.drop_constraint('fk_liq_mandato_inversionista', 'liquidacion_mandatos', type_='foreignkey')
    op.drop_column('liquidacion_mandatos', 'inversionista_id')
    # Los valores de enum no se pueden eliminar en Postgres fácilmente; downgrade los omite.
