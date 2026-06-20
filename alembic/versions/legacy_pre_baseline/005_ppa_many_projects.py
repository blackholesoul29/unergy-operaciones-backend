"""ppa_contratos: relación muchos-a-muchos con proyectos, eliminar tipo_contrato

Revision ID: 005
Revises: 004
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Eliminar tipo_contrato de ppa_contratos ───────────────────────────────
    op.drop_column('ppa_contratos', 'tipo_contrato')

    # ── Eliminar proyecto_id (FK 1→1) de ppa_contratos ───────────────────────
    op.drop_constraint('ppa_contratos_proyecto_id_fkey', 'ppa_contratos', type_='foreignkey')
    op.drop_column('ppa_contratos', 'proyecto_id')

    # ── Tabla de asociación muchos-a-muchos PPA ↔ Proyectos ──────────────────
    op.create_table(
        'ppa_contrato_proyectos',
        sa.Column('contrato_id', sa.BigInteger(), sa.ForeignKey('ppa_contratos.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('proyecto_id', sa.BigInteger(), sa.ForeignKey('proyectos.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_index('ix_ppa_cp_contrato', 'ppa_contrato_proyectos', ['contrato_id'])
    op.create_index('ix_ppa_cp_proyecto', 'ppa_contrato_proyectos', ['proyecto_id'])


def downgrade() -> None:
    op.drop_index('ix_ppa_cp_proyecto', table_name='ppa_contrato_proyectos')
    op.drop_index('ix_ppa_cp_contrato', table_name='ppa_contrato_proyectos')
    op.drop_table('ppa_contrato_proyectos')

    op.add_column('ppa_contratos', sa.Column('proyecto_id', sa.BigInteger(), nullable=True))
    op.add_column('ppa_contratos', sa.Column('tipo_contrato', sa.String(20), nullable=True))
