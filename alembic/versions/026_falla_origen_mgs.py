"""Eventos críticos MGS — origen y subtipo de alerta en fallas

Marca el origen de cada falla (MANUAL vs MGS_CRITICA) y el subtipo de alerta del
monitoreo (CAIDA_PRODUCCION / DESCONEXION_TOTAL) para las fallas generadas
automáticamente por el detector de eventos críticos del MGS. Idempotente.

NOTA: el esquema de producción se provisiona vía _PENDING_DDLS en app/main.py
(Alembic está roto: heads múltiples). Esta migración es solo de registro.

El enlace al proyecto afectado (proyecto_id) ya existe en la tabla fallas y la
URL de detalle de la notificación reutiliza la columna existente
notificaciones.link, por lo que no se agregan columnas adicionales.

Revision ID: 026
Revises: 025
Create Date: 2026-06-25
"""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE fallas ADD COLUMN IF NOT EXISTS origen VARCHAR(50) NOT NULL DEFAULT 'MANUAL'")
    op.execute("ALTER TABLE fallas ADD COLUMN IF NOT EXISTS tipo_alerta_mgs VARCHAR(50)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_fallas_origen ON fallas (origen)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_fallas_origen")
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS tipo_alerta_mgs")
    op.execute("ALTER TABLE fallas DROP COLUMN IF EXISTS origen")
