"""Detalles operacionales y contractuales del contrato de servicio.

Agrega cuatro columnas de texto libre a `contratos_servicio`:
`service_scope` (alcance del servicio), `specific_service_terms`
(términos específicos), `slas` (acuerdos de nivel de servicio) y
`responsibilities` (responsabilidades de las partes).

Estos campos ya se capturan en el wizard del frontend y se muestran en el
detalle del contrato, pero hasta ahora no existían en el backend: el POST los
enviaba y Pydantic los descartaba silenciosamente (data loss). Esta migración
cierra el contrato front↔back.

ADD COLUMN IF NOT EXISTS en cada paso para que reintentar la migración desde
cero sea seguro si un deploy se corta a medias (mismo criterio que 034).

Revision ID: 053
Revises: 047
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    for col in ("service_scope", "specific_service_terms", "slas", "responsibilities"):
        conn.execute(sa.text(
            f"ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS {col} TEXT"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    for col in ("responsibilities", "slas", "specific_service_terms", "service_scope"):
        conn.execute(sa.text(
            f"ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS {col}"
        ))
