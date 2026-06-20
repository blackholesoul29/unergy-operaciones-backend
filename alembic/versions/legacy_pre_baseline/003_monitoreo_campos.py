"""monitoreo: fotos/centinela/notificacion en fallas, tabla generacion_diaria, alias en proyectos

Revision ID: 003
Revises: 002
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003a'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fallas: nuevos campos para integración monitoreo ─────────────────────────
    op.add_column('fallas', sa.Column('fotos_urls', sa.Text(), nullable=True))
    op.add_column('fallas', sa.Column('centinela', sa.String(200), nullable=True))
    op.add_column('fallas', sa.Column('notificacion', sa.Boolean(), server_default='false', nullable=False))

    # ── proyectos: alias de nombre para matching con data externa ─────────────────
    op.add_column('proyectos', sa.Column('alias_monitoreo', sa.Text(), nullable=True))

    # ── tabla generacion_diaria ───────────────────────────────────────────────────
    op.create_table(
        'generacion_diaria',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('proyecto_id', sa.BigInteger(), sa.ForeignKey('proyectos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('kwh_real', sa.Numeric(14, 3), nullable=True),
        sa.Column('kwh_p90', sa.Numeric(14, 3), nullable=True),
        sa.Column('kwh_autoconsumo', sa.Numeric(14, 3), nullable=True),
        sa.Column('fuente', sa.String(50), server_default='manual', nullable=False),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_generacion_proyecto_fecha', 'generacion_diaria', ['proyecto_id', 'fecha'])
    op.create_index('ix_generacion_proyecto_fecha', 'generacion_diaria', ['proyecto_id', 'fecha'])
    op.create_index('ix_generacion_fecha', 'generacion_diaria', ['fecha'])

    # ── tabla monitoreo_verificaciones (códigos 6 dígitos para clientes) ─────────
    op.create_table(
        'monitoreo_verificaciones',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, index=True),
        sa.Column('codigo', sa.String(6), nullable=False),
        sa.Column('usado', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('monitoreo_verificaciones')
    op.drop_index('ix_generacion_fecha', table_name='generacion_diaria')
    op.drop_index('ix_generacion_proyecto_fecha', table_name='generacion_diaria')
    op.drop_constraint('uq_generacion_proyecto_fecha', 'generacion_diaria', type_='unique')
    op.drop_table('generacion_diaria')
    op.drop_column('proyectos', 'alias_monitoreo')
    op.drop_column('fallas', 'notificacion')
    op.drop_column('fallas', 'centinela')
    op.drop_column('fallas', 'fotos_urls')
