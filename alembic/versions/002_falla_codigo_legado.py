"""add codigo_legado to fallas

Revision ID: 002
Revises: 001
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fallas', sa.Column('codigo_legado', sa.String(30), nullable=True))
    op.create_unique_constraint('uq_fallas_codigo_legado', 'fallas', ['codigo_legado'])
    op.create_index('ix_fallas_codigo_legado', 'fallas', ['codigo_legado'])


def downgrade() -> None:
    op.drop_index('ix_fallas_codigo_legado', table_name='fallas')
    op.drop_constraint('uq_fallas_codigo_legado', 'fallas', type_='unique')
    op.drop_column('fallas', 'codigo_legado')
