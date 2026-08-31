"""drop contratos_servicio.facturas_solenium/facturas_inversionistas (migradas)

Los datos ya se movieron a la tabla contrato_factura (migracion 131 +
scripts/migrar_facturas_a_contrato_factura.py, corrido en produccion el
2026-08-31: 343 filas migradas, 5 proyectos sin contrato de mantenimiento
quedaron pendientes -- ver scripts/data/*.json, que se conservan como
respaldo). El modelo ORM ya no mapea estas 2 columnas desde el commit que
creo ContratoFactura.

Revision ID: 132
Revises: 131
Create Date: 2026-08-31
"""
from alembic import op

revision = "132"
down_revision = "131"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS facturas_solenium")
    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS facturas_inversionistas")


def downgrade():
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS facturas_solenium JSONB")
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS facturas_inversionistas JSONB")
