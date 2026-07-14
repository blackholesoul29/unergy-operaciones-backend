"""San Pedro operativo en Generacion Solar — identificado por su Solenium id.

Corrige la 041, que filtraba por nombre (ILIKE '%san pedro%') y quedaba en
no-op si el nombre_comercial real no coincidia exactamente (acentos, prefijos
"MGS 0003", etc.).

San Pedro tiene project_id_solenium = '118' (sembrado en la 012), columna
UNIQUE, asi que es el identificador fiable: no depende del nombre y no puede
afectar a otro proyecto. Deja las 3 condiciones que faltaban para el monitoreo
de flota (estado, tipo_proyecto, srv_operacion). El medidor (nodo Gaia 616) se
resuelve solo via su frontera de generacion.

Idempotente. Si '118' no estuviera asignado en la BD (no deberia), es no-op y
el problema seria el vinculo Solenium, no este UPDATE.

Revision ID: 042
Revises: 041
Create Date: 2026-07-08
"""
from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE proyectos
        SET estado = 'en_operacion'::estado_proyecto_enum,
            tipo_proyecto = 'minigranja'::tipo_proyecto_enum,
            srv_operacion = true
        WHERE project_id_solenium = '118'
          AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # Migracion de datos: no se revierte (no guardamos el estado previo).
    pass
