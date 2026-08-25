"""drop proyecto_grupos_panel (0 filas, sin UI, cero adopcion)

Modelo ProyectoGrupoPanel + tabla proyecto_grupos_panel + los 4 endpoints
CRUD (/proyectos/{id}/grupos-panel...). Cero filas en produccion desde
que existe la tabla (migracion 007), y no aparece en ningun archivo del
frontend -- ni siquiera _ficha_tecnica() de comercial.py (el unico
consumidor real, para el arbol /comercial/proyectos-operando) lo mostraba
a nadie, ya que el JSON resultante ("paneles.grupos") tampoco lo lee el
frontend. El conteo/marca/potencia de paneles sigue viniendo de
proyecto_info_tecnica (cantidad_total_paneles, marca_paneles,
potencia_panel_kwp), que si tiene adopcion real.

Revision ID: 067
Revises: 066
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("proyecto_grupos_panel")


def downgrade():
    op.create_table(
        "proyecto_grupos_panel",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("proyecto_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=False, index=True),
        sa.Column("marca", sa.String(length=255), nullable=True),
        sa.Column("modelo", sa.String(length=255), nullable=True),
        sa.Column("potencia_pico_wp", sa.Numeric(10, 2), nullable=True),
        sa.Column("cantidad", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
