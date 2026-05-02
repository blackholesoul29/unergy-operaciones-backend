"""ppa_contratos: comprador/vendedor, nombre_interno, indexación base, tiempo_pago, tablas hijas tarifas y compromisos

Revision ID: 004
Revises: 003
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ppa_contratos: eliminar campos contraparte y gescon_codigos_sic ──────────
    op.drop_column('ppa_contratos', 'contraparte_nombre')
    op.drop_column('ppa_contratos', 'contraparte_nit')
    op.drop_column('ppa_contratos', 'gescon_codigos_sic')

    # ── ppa_contratos: nuevos campos ─────────────────────────────────────────────
    op.add_column('ppa_contratos', sa.Column('nombre_interno', sa.String(200), nullable=True))
    op.add_column('ppa_contratos', sa.Column('comprador_nombre', sa.String(255), nullable=True))
    op.add_column('ppa_contratos', sa.Column('comprador_nit', sa.String(20), nullable=True))
    op.add_column('ppa_contratos', sa.Column('vendedor_nombre', sa.String(255), nullable=True))
    op.add_column('ppa_contratos', sa.Column('vendedor_nit', sa.String(20), nullable=True))
    op.add_column('ppa_contratos', sa.Column('periodo_indexacion_base', sa.String(7), nullable=True))
    op.add_column('ppa_contratos', sa.Column('valor_indexacion_base', sa.Numeric(12, 4), nullable=True))
    op.add_column('ppa_contratos', sa.Column('codigo_sic', sa.String(50), nullable=True))
    op.add_column('ppa_contratos', sa.Column('tiempo_pago', sa.Integer(), nullable=True))

    # ── tabla ppa_tarifas ─────────────────────────────────────────────────────────
    op.create_table(
        'ppa_tarifas',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('contrato_id', sa.BigInteger(), sa.ForeignKey('ppa_contratos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('año', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('tarifa', sa.Numeric(12, 4), nullable=True),
    )
    op.create_unique_constraint('uq_ppa_tarifa_contrato_periodo', 'ppa_tarifas', ['contrato_id', 'año', 'mes'])
    op.create_index('ix_ppa_tarifas_contrato', 'ppa_tarifas', ['contrato_id'])

    # ── tabla ppa_compromisos_energia ─────────────────────────────────────────────
    op.create_table(
        'ppa_compromisos_energia',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('contrato_id', sa.BigInteger(), sa.ForeignKey('ppa_contratos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('año', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('energia_minima', sa.Numeric(14, 3), nullable=True),
        sa.Column('energia_maxima', sa.Numeric(14, 3), nullable=True),
        sa.Column('cantidad_proyectos', sa.Integer(), nullable=True),
    )
    op.create_unique_constraint('uq_ppa_compromiso_contrato_periodo', 'ppa_compromisos_energia', ['contrato_id', 'año', 'mes'])
    op.create_index('ix_ppa_compromisos_contrato', 'ppa_compromisos_energia', ['contrato_id'])


def downgrade() -> None:
    op.drop_index('ix_ppa_compromisos_contrato', table_name='ppa_compromisos_energia')
    op.drop_constraint('uq_ppa_compromiso_contrato_periodo', 'ppa_compromisos_energia', type_='unique')
    op.drop_table('ppa_compromisos_energia')

    op.drop_index('ix_ppa_tarifas_contrato', table_name='ppa_tarifas')
    op.drop_constraint('uq_ppa_tarifa_contrato_periodo', 'ppa_tarifas', type_='unique')
    op.drop_table('ppa_tarifas')

    op.drop_column('ppa_contratos', 'tiempo_pago')
    op.drop_column('ppa_contratos', 'codigo_sic')
    op.drop_column('ppa_contratos', 'valor_indexacion_base')
    op.drop_column('ppa_contratos', 'periodo_indexacion_base')
    op.drop_column('ppa_contratos', 'vendedor_nit')
    op.drop_column('ppa_contratos', 'vendedor_nombre')
    op.drop_column('ppa_contratos', 'comprador_nit')
    op.drop_column('ppa_contratos', 'comprador_nombre')
    op.drop_column('ppa_contratos', 'nombre_interno')

    op.add_column('ppa_contratos', sa.Column('gescon_codigos_sic', sa.String(500), nullable=True))
    op.add_column('ppa_contratos', sa.Column('contraparte_nit', sa.String(20), nullable=True))
    op.add_column('ppa_contratos', sa.Column('contraparte_nombre', sa.String(255), nullable=True))
