"""Eliminar notificaciones.link (nunca consumido en frontend)

Auditoria de la tabla notificaciones 2026-08-31: el backend la llena en
las 4 fuentes que crean notificaciones (alarmas de desconexion, alarmas
de comunicacion de fallas, "nueva falla registrada", "falla asignada a
ti") con rutas reales (/proyectos/{id}, /m/tecnico, /m/coordinador), pero
ni NotificationsBell.vue (escritorio) ni NotificationsSheet.vue (movil)
la leen -- al hacer click en una notificacion, ambos solo la marcan como
leida, nunca navegan a donde apunta. Dato guardado y enviado sin ningun
consumidor real.

Revision ID: 134
Revises: 133
Create Date: 2026-08-31
"""
from alembic import op

revision = "134"
down_revision = "133"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE notificaciones DROP COLUMN IF EXISTS link")


def downgrade():
    op.execute("ALTER TABLE notificaciones ADD COLUMN IF NOT EXISTS link VARCHAR(1000)")
