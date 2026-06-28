"""arr_documento: agregar nombre_original (nombre subido por el usuario).

``nombre_archivo`` guarda el nombre mostrado/renombrado en disco; ``nombre_original``
conserva el nombre real que subió el usuario, para descargas más amigables y trazabilidad.

Revision ID: 031
Revises: 030
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arr_documento", sa.Column("nombre_original", sa.String(500), nullable=True))
    # Backfill: usar el nombre_archivo existente como nombre original para filas previas.
    op.execute("UPDATE arr_documento SET nombre_original = nombre_archivo WHERE nombre_original IS NULL")
    op.alter_column("arr_documento", "nombre_original", existing_type=sa.String(500), nullable=False)


def downgrade() -> None:
    op.drop_column("arr_documento", "nombre_original")
