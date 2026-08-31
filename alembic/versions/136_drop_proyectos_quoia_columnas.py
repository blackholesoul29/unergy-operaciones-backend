"""Eliminar proyectos.quoia_reporte_generacion_id/consumo_id/nodo_id (muertas)

Auditoria 2026-08-31 (parte de la revision de alarmas_monitoreo/alarm_engine):
estas 3 columnas estaban 100% vacias en produccion (0/188 proyectos) y su
unico escritor era la pestana "ID Quoia" del detalle de proyecto, que
mandaba PATCH /proyectos/{id}. Nunca hubo sincronizacion real con los ids de
Quoia de verdad, que viven por SUBPROYECTO en la API externa de
Liquidaciones (api.unergy.io, ver app/services/liquidaciones_api.py) y a los
que la vista de lista "IDs proyectos" ya les daba prioridad de lectura sobre
estas columnas -- el endpoint PATCH /liquidaciones-api/subproyectos/{topico}
existia pero ningun formulario lo llamaba. Se redirigio la pestana "ID
Quoia" a ese endpoint (frontend) en vez de seguir escribiendo aca.

Revision ID: 136
Revises: 135
Create Date: 2026-08-31
"""
from alembic import op

revision = "136"
down_revision = "135"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS quoia_reporte_generacion_id")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS quoia_reporte_consumo_id")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS quoia_nodo_id")


def downgrade():
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_reporte_generacion_id INTEGER")
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_reporte_consumo_id INTEGER")
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_nodo_id INTEGER")
