"""add om_pagina_sin_match table

Motivo: las paginas del PDF consolidado de Mantenimiento que no logran
emparejarse a un contrato (sin_match) solo vivian en la respuesta HTTP del
momento del upload -- no habia forma de revisarlas despues ni de asignarlas
manualmente a un proyecto. Esta tabla las persiste para poder mostrarlas en
Proveedor entre recargas y resolverlas via PATCH /om/factura/{periodo}/sin-match/{id}/asignar.

Revision ID: 049
Revises: 048
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "om_pagina_sin_match",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("pagina", sa.Integer, nullable=False),
        sa.Column("nombre_extraido", sa.String(300), nullable=True),
        sa.Column("estrategia", sa.String(30), nullable=True),
        sa.Column("razon", sa.String(200), nullable=False),
        sa.Column("numero_factura", sa.String(30), nullable=True),
        sa.Column("muestra_texto", sa.String(500), nullable=True),
        sa.Column("origen", sa.String(20), nullable=False, server_default="upload"),
        sa.Column("resuelto", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("contrato_id_asignado", sa.BigInteger,
                  sa.ForeignKey("contratos_servicio.id"), nullable=True),
        sa.Column("asignado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("periodo", "pagina",
                            name="uq_om_sin_match_periodo_pagina"),
    )


def downgrade() -> None:
    op.drop_table("om_pagina_sin_match")
