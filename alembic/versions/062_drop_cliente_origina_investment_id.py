"""Elimina clientes.origina_investment_id (integracion Origina abandonada).

Motivo: el vinculo con el fondo de inversion en Origina (correlate_investments,
GET /clientes/{id}/fondos, GET /correlation/fondos*) nunca llego a tener una
pantalla en el frontend que lo mostrara -- 11 clientes tenian el campo
poblado, pero ese dato era invisible para cualquiera. La integracion con
originabotdb ya esta confirmada rota (inalcanzable desde Railway, ver
_origina_conn) y en proceso de abandono (el pipeline de energizacion que si
importaba ya se migro a Sun Factory/TSF). Se decidio con el usuario
eliminar esta relacion en vez de arreglarla.

Revision ID: 062
Revises: 061
Create Date: 2026-08-19
"""
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clientes_origina_investment")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS origina_investment_id")


def downgrade() -> None:
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS origina_investment_id BIGINT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_clientes_origina_investment "
        "ON clientes (origina_investment_id) WHERE origina_investment_id IS NOT NULL"
    )
