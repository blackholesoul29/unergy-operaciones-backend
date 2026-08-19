"""Agrega arr_arrendador_id a ArrSeleccion/ArrDocumento y ajusta UniqueConstraint.

Revision ID: 053
Revises: 052
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from alembic_idempotencia import agregar_columna_si_falta, constraint_existe

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    agregar_columna_si_falta(bind, "arr_seleccion_mensual", sa.Column("arr_arrendador_id", sa.BigInteger, sa.ForeignKey("arr_arrendador.id", ondelete="CASCADE"), nullable=True))
    agregar_columna_si_falta(bind, "arr_documento", sa.Column("arr_arrendador_id", sa.BigInteger, sa.ForeignKey("arr_arrendador.id", ondelete="CASCADE"), nullable=True))

    if constraint_existe(bind, "arr_seleccion_mensual", "uq_arr_seleccion_proyecto_periodo"):
        op.drop_constraint("uq_arr_seleccion_proyecto_periodo", "arr_seleccion_mensual", type_="unique")
    if not constraint_existe(bind, "arr_seleccion_mensual", "uq_arr_seleccion_arrendador_periodo"):
        op.create_unique_constraint("uq_arr_seleccion_arrendador_periodo", "arr_seleccion_mensual", ["arr_arrendador_id", "periodo"])

    if constraint_existe(bind, "arr_documento", "uq_arr_doc_proyecto_periodo_pago"):
        op.drop_constraint("uq_arr_doc_proyecto_periodo_pago", "arr_documento", type_="unique")
    if not constraint_existe(bind, "arr_documento", "uq_arr_doc_proyecto_periodo_pago_arrendador"):
        op.create_unique_constraint("uq_arr_doc_proyecto_periodo_pago_arrendador", "arr_documento", ["arr_proyecto_id", "periodo", "pago_id", "arr_arrendador_id"])


def downgrade() -> None:
    op.drop_constraint("uq_arr_doc_proyecto_periodo_pago_arrendador", "arr_documento", type_="unique")
    op.create_unique_constraint("uq_arr_doc_proyecto_periodo_pago", "arr_documento", ["arr_proyecto_id", "periodo", "pago_id"])
    op.drop_constraint("uq_arr_seleccion_arrendador_periodo", "arr_seleccion_mensual", type_="unique")
    op.create_unique_constraint("uq_arr_seleccion_proyecto_periodo", "arr_seleccion_mensual", ["arr_proyecto_id", "periodo"])
    op.drop_column("arr_documento", "arr_arrendador_id")
    op.drop_column("arr_seleccion_mensual", "arr_arrendador_id")
