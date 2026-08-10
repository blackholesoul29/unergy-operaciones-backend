"""Elimina el portal de monitoreo de clientes (login por correo) y el campo
correo_electronico de clientes.

Motivo: el portal (static/monitoreo/index.html, servido en GET /monitoreo,
con los endpoints /monitoreo/proyectos, /monitoreo/generacion, /monitoreo/auth/*
y /monitoreo/fallas*) ya no lo usa nadie -- confirmado por el usuario. El campo
correo_electronico solo servia como llave de busqueda para ese portal y como
match secundario (tras NIT) en la conciliacion con Origina (correlate_investments,
ya actualizado para no depender de el). Solo 1 cliente tenia el campo cargado.

Revision ID: 048
Revises: 047
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS correo_electronico")
    op.execute("DROP TABLE IF EXISTS monitoreo_verificaciones")


def downgrade() -> None:
    op.add_column("clientes", sa.Column("correo_electronico", sa.String(255), nullable=True))
    op.create_table(
        "monitoreo_verificaciones",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("codigo", sa.String(6), nullable=False),
        sa.Column("usado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_monitoreo_ver_email", "monitoreo_verificaciones", ["email"])
