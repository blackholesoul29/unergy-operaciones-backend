"""liquidaciones: nuevos tipos ingreso/costo, inversionista_id, soporte_url

Revision ID: 003
Revises: 002
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa

revision = '003b'
down_revision = '003a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Nuevos valores en tipo_linea_mandato_enum ---
    for val in ('despacho', 'ventas_en_bolsa', 'compras_en_bolsa',
                'redistribucion_ingresos', 'cambio_equipos_medida'):
        op.execute(f"""
            DO $$ BEGIN
                ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS '{val}';
            EXCEPTION WHEN undefined_object THEN NULL; END $$
        """)

    # --- Nuevo valor en tipo_costo_enum ---
    op.execute("""
        DO $$ BEGIN
            ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida';
        EXCEPTION WHEN undefined_object THEN NULL; END $$
    """)

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
