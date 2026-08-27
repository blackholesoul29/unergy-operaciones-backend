"""proyecto_inicio_operacion: eliminar pruebas/documentos (sin lector)

Auditoria de Proyectos 2026-08-27. La vista que editaba estos dos campos
JSONB (InicioOperacionView.vue) se retiro del frontend el 2026-08-21
(commit 9ef45b1) y su router se desmonto de la API el mismo dia (commit
c5b00ca). De los 4 campos JSONB de la tabla, `checklist` y `pendientes`
siguen usandose (informe_om.py los lee para el detalle y los 4 semaforos
derivados), pero `pruebas` y `documentos` no tienen ningun lector, ni en
el frontend actual ni en el propio informe_om.py.

Revision ID: 117
Revises: 116
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for col in ("pruebas", "documentos"):
        if columna_existe(bind, "proyecto_inicio_operacion", col):
            op.execute(f"ALTER TABLE proyecto_inicio_operacion DROP COLUMN {col}")


def downgrade():
    # Sin lector en todo el frontend actual: no hay nada que valga la pena
    # recrear.
    pass
