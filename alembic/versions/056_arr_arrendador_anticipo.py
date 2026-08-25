"""Agrega anticipo_pagado_desde/hasta y observaciones a ArrArrendador.

Revision ID: 056
Revises: 055
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from alembic_idempotencia import agregar_columna_si_falta

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    agregar_columna_si_falta(bind, "arr_arrendador", sa.Column("anticipo_pagado_desde", sa.Date, nullable=True))
    agregar_columna_si_falta(bind, "arr_arrendador", sa.Column("anticipo_pagado_hasta", sa.Date, nullable=True))
    agregar_columna_si_falta(bind, "arr_arrendador", sa.Column("observaciones", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("arr_arrendador", "observaciones")
    op.drop_column("arr_arrendador", "anticipo_pagado_hasta")
    op.drop_column("arr_arrendador", "anticipo_pagado_desde")
