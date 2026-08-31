"""eliminar contratos_servicio.canones_otros (write-only, sin uso)

Auditoria de campos de ContratoServicio 2026-08-28. `canones_otros` esta en
0/162 y, a diferencia de `fecha_indexacion` (se muestra en ClienteResumen.vue)
y `facturas_solenium` (feature completo, FacturasMantenimiento.vue), no tiene
ninguna pantalla que lo lea: solo se escribe desde el wizard. Tampoco lo usa
el calculo de "canon" de Arriendos/OM (ese sale de tarifa_mensual +
indexacion, confirmado en arriendos.py/om.py).

Revision ID: 128
Revises: 127
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM contratos_servicio WHERE canones_otros IS NOT NULL"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 128: contratos_servicio tiene {n} fila(s) con "
            f"canones_otros poblado -- se esperaba 0. Revisar a mano antes "
            f"de eliminar."
        )

    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS canones_otros")


def downgrade():
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS canones_otros NUMERIC(12,4)")
