"""Elimina proyectos.cantidad_total_paneles (duplicado huerfano).

Motivo: el mismo dato vive en proyecto_info_tecnica.cantidad_total_paneles
(migracion 016), que es la unica con un formulario real que lo edita
(ProyectoForm.vue / ProyectoDetailView.vue, pestana Tecnico). La columna en
`proyectos` nunca tuvo UI que la escribiera -- solo se llenaba via el
endpoint temporal de backfill /monitoreo/admin/sync-proyectos, que ya se
actualizo para escribir unicamente en proyecto_info_tecnica.

Revision ID: 061
Revises: 060
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS cantidad_total_paneles")


def downgrade() -> None:
    op.add_column("proyectos", sa.Column("cantidad_total_paneles", sa.Integer, nullable=True))
