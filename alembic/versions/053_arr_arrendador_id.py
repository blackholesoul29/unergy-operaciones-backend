"""Agrega arr_arrendador_id a ArrSeleccion/ArrDocumento y ajusta UniqueConstraint.

Revision ID: 053
Revises: 052
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arr_seleccion_mensual", sa.Column("arr_arrendador_id", sa.BigInteger, sa.ForeignKey("arr_arrendador.id", ondelete="CASCADE"), nullable=True))
    op.add_column("arr_documento", sa.Column("arr_arrendador_id", sa.BigInteger, sa.ForeignKey("arr_arrendador.id", ondelete="CASCADE"), nullable=True))
    op.drop_constraint("uq_arr_seleccion_proyecto_periodo", "arr_seleccion_mensual", type_="unique")
    op.create_unique_constraint("uq_arr_seleccion_arrendador_periodo", "arr_seleccion_mensual", ["arr_arrendador_id", "periodo"])
    op.drop_constraint("uq_arr_doc_proyecto_periodo_pago", "arr_documento", type_="unique")
    op.create_unique_constraint("uq_arr_doc_proyecto_periodo_pago_arrendador", "arr_documento", ["arr_proyecto_id", "periodo", "pago_id", "arr_arrendador_id"])


def downgrade() -> None:
    op.drop_constraint("uq_arr_doc_proyecto_periodo_pago_arrendador", "arr_documento", type_="unique")
    op.create_unique_constraint("uq_arr_doc_proyecto_periodo_pago", "arr_documento", ["arr_proyecto_id", "periodo", "pago_id"])
    op.drop_constraint("uq_arr_seleccion_arrendador_periodo", "arr_seleccion_mensual", type_="unique")
    op.create_unique_constraint("uq_arr_seleccion_proyecto_periodo", "arr_seleccion_mensual", ["arr_proyecto_id", "periodo"])
    op.drop_column("arr_documento", "arr_arrendador_id")
    op.drop_column("arr_seleccion_mensual", "arr_arrendador_id")
