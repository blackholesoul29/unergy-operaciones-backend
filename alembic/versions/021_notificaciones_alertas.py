"""Crear tabla notificaciones_alertas

Revision ID: 021
Revises: 020
Create Date: 2026-06-14
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notificaciones_alertas (
            id             BIGSERIAL PRIMARY KEY,
            usuario_id     BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            alerta_ref     VARCHAR(255),
            titulo         VARCHAR(255) NOT NULL,
            mensaje        TEXT NOT NULL,
            severidad      VARCHAR(20) NOT NULL DEFAULT 'critica',
            canal          VARCHAR(20) NOT NULL DEFAULT 'in_app',
            leida          BOOLEAN NOT NULL DEFAULT FALSE,
            email_enviado  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            leida_at       TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notificaciones_alertas_usuario "
        "ON notificaciones_alertas(usuario_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notif_alertas_usuario_leida "
        "ON notificaciones_alertas(usuario_id, leida)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notificaciones_alertas")
