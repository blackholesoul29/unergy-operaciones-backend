"""eliminar cgm_porcentaje_fncer/cgm_tipo_asignacion (sin uso, ni en el unico caso real de CGM)

Auditoria de campos de ContratoServicio 2026-08-28. `tiene_cgm`/`cgm_codigo_sic`
se conservan: SI tienen un caso real (contrato #1, representacion, codigo SIC
UNERGY-RC-014-2025). Pero `cgm_porcentaje_fncer` y `cgm_tipo_asignacion` estan
en 0/162 -- incluso ese unico contrato con CGM real nunca los uso. Ademas,
ningun lugar del frontend los muestra (solo se escriben desde el wizard, nunca
se leen en ninguna vista de detalle).

Revision ID: 127
Revises: 126
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM contratos_servicio "
        "WHERE cgm_porcentaje_fncer IS NOT NULL OR cgm_tipo_asignacion IS NOT NULL"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 127: contratos_servicio tiene {n} fila(s) con "
            f"cgm_porcentaje_fncer/cgm_tipo_asignacion pobladas -- se esperaba "
            f"0. Revisar a mano antes de eliminar."
        )

    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS cgm_porcentaje_fncer")
    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS cgm_tipo_asignacion")


def downgrade():
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS cgm_porcentaje_fncer NUMERIC(5,2)")
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS cgm_tipo_asignacion VARCHAR(100)")
