"""San Pedro (id 45) visible en Operaciones -> Generacion Solar.

El monitoreo de flota (GET /generacion-solar/monitoring) solo lista proyectos
que cumplen TODAS estas condiciones:
    estado = 'en_operacion'
    tipo_proyecto = 'minigranja'
    project_id_solenium IS NOT NULL
    srv_operacion = true

Minigranja Solar San Pedro (proyecto id 45) ya tiene su project_id_solenium
sembrado en la migracion 012 (Solenium id 118, = "ID de inversores"), y ya
cuenta con su frontera de generacion (de donde se resuelve solo el medidor,
nodo Gaia 616). Solo faltaba dejar los otros tres campos como en cualquier
minigranja operativa. Este UPDATE los fija de forma idempotente.

Se guarda con id = 45 AND nombre ILIKE '%san pedro%' para ser no-op si la
fila no correspondiera a San Pedro (mismo criterio que la 012).

Revision ID: 041
Revises: 040
Create Date: 2026-07-08
"""
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE proyectos
        SET project_id_solenium = '118',
            tipo_proyecto = 'minigranja'::tipo_proyecto_enum,
            estado = 'en_operacion'::estado_proyecto_enum,
            srv_operacion = true
        WHERE id = 45
          AND nombre_comercial ILIKE '%san pedro%'
          AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # Migracion de datos: no se revierte automaticamente (no guardamos el
    # estado previo). No-op intencional.
    pass
