"""Elimina operadores_red_contactos.activo: nunca se expuso en la API ni en
el frontend, y el envio del Reporte CGM nunca lo filtro -- pausar un contacto
sin borrarlo no es una funcion que exista hoy, asi que el campo solo quedaba
como ruido en el esquema.

Revision ID: 077
Revises: 076
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("operadores_red_contactos", "activo")


def downgrade() -> None:
    op.add_column(
        "operadores_red_contactos",
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
    )
