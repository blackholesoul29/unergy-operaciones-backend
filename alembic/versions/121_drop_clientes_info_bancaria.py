"""clientes: eliminar banco/tipo_cuenta/numero_cuenta/titular_cuenta (sin uso)

Auditoria de Clientes 2026-08-28. Seccion completa "Informacion bancaria"
en ClienteForm.vue, escribible, pero nunca mostrada en ningun lado (ni
detalle, ni checklist de completitud, ni ninguna otra vista). 0/96
clientes activos en produccion tenian alguno de estos 4 campos cargado.

Revision ID: 121
Revises: 120
Create Date: 2026-08-28
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for col in ("banco", "tipo_cuenta", "numero_cuenta", "titular_cuenta"):
        if columna_existe(bind, "clientes", col):
            op.execute(f"ALTER TABLE clientes DROP COLUMN {col}")


def downgrade():
    # 0/96 poblado siempre: no hay nada que valga la pena recrear.
    pass
