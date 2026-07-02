"""Catálogo de Operadores de Red y sus contactos, + vínculo fronteras.operador_red_id.

Primer paso de la integración del reporte CGM a la plataforma (envío del
reporte a los operadores de red). fronteras.operador_red sigue existiendo
como texto (viene de GESCON, ya es confiable) -- esta migración agrega la
relación estructurada por encima, sin duplicar el dato en `proyectos` para
no repetir el problema de sincronización que se corrigió hoy con
fronteras.proyecto_id.

Revision ID: 033
Revises: 032
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operadores_red",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre_legal", sa.String(255), nullable=False, unique=True),
        sa.Column("nombre_comercial", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "operadores_red_contactos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("operador_red_id", sa.BigInteger(),
                  sa.ForeignKey("operadores_red.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("nombre", sa.String(255), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "fronteras",
        sa.Column("operador_red_id", sa.BigInteger(),
                  sa.ForeignKey("operadores_red.id"), nullable=True),
    )
    op.create_index("ix_fronteras_operador_red_id", "fronteras", ["operador_red_id"])

    # Seed: los operadores reales que ya aparecen en fronteras.operador_red
    # (texto de GESCON). nombre_comercial solo se pone cuando ya se veía usado
    # en proyectos.operador_red (Afinia/Air-e/ESSA) -- para los otros 4 no se
    # inventa un nombre comercial sin confirmar.
    operadores = [
        ("CARIBEMAR DE LA COSTA S.A.S. E.S.P. - DISTRIBUIDOR", "Afinia"),
        ("AIR-E S.A.S. E.S.P. - DISTRIBUIDOR", "Air-e"),
        ("ELECTRIFICADORA DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR", "ESSA"),
        ("CENTRALES ELECTRICAS DE NARIÑO S.A. E.S.P. - DISTRIBUIDOR", None),
        ("CENTRALES ELECTRICAS DEL NORTE DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR", None),
        ("EMPRESA DE ENERGIA DE CASANARE S.A. E.S.P. - DISTRIBUIDOR", None),
        ("EMPRESAS PUBLICAS DE MEDELLIN E.S.P. - DISTRIBUIDOR", None),
    ]
    conn = op.get_bind()
    op_table = sa.table(
        "operadores_red",
        sa.column("id", sa.BigInteger),
        sa.column("nombre_legal", sa.String),
        sa.column("nombre_comercial", sa.String),
    )
    for nombre_legal, nombre_comercial in operadores:
        conn.execute(
            op_table.insert().values(nombre_legal=nombre_legal, nombre_comercial=nombre_comercial)
        )

    # Backfill: fronteras.operador_red_id a partir del texto ya existente
    # (match exacto -- ambos valores vienen literalmente de GESCON, sin
    # necesidad de fuzzy matching).
    conn.execute(sa.text("""
        UPDATE fronteras f
        SET operador_red_id = o.id
        FROM operadores_red o
        WHERE f.operador_red = o.nombre_legal
    """))


def downgrade() -> None:
    op.drop_index("ix_fronteras_operador_red_id", table_name="fronteras")
    op.drop_column("fronteras", "operador_red_id")
    op.drop_table("operadores_red_contactos")
    op.drop_table("operadores_red")
