"""Completar nombre_comercial de los 4 operadores de red que faltaban.

La migración 033 dejó estos 4 sin nombre comercial a propósito ("no se
inventa un nombre comercial sin confirmar"). Ya confirmado por la usuaria.

Revision ID: 036
Revises: 035
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


NOMBRES_COMERCIALES = {
    "CENTRALES ELECTRICAS DE NARIÑO S.A. E.S.P. - DISTRIBUIDOR": "CEDENAR",
    "CENTRALES ELECTRICAS DEL NORTE DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR": "CENS",
    "EMPRESA DE ENERGIA DE CASANARE S.A. E.S.P. - DISTRIBUIDOR": "ENERCA",
    "EMPRESAS PUBLICAS DE MEDELLIN E.S.P. - DISTRIBUIDOR": "EPM",
}


def upgrade() -> None:
    conn = op.get_bind()
    for nombre_legal, nombre_comercial in NOMBRES_COMERCIALES.items():
        conn.execute(sa.text(
            "UPDATE operadores_red SET nombre_comercial = :comercial WHERE nombre_legal = :legal"
        ), {"comercial": nombre_comercial, "legal": nombre_legal})


def downgrade() -> None:
    conn = op.get_bind()
    for nombre_legal in NOMBRES_COMERCIALES:
        conn.execute(sa.text(
            "UPDATE operadores_red SET nombre_comercial = NULL WHERE nombre_legal = :legal"
        ), {"legal": nombre_legal})
