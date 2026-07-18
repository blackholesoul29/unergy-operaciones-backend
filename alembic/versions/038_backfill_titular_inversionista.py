"""Backfillear proyecto_inversionistas para proyectos que solo tenían titular.

app/services/contactos.py deja de usar Proyecto.cliente_id (titular) para
resolver contactos por defecto -- ahora depende exclusivamente de
ProyectoInversionista. Confirmado en producción: de 184 proyectos, 13 tienen
titular pero ninguna fila en proyecto_inversionistas (se quedarían sin
contactos por defecto). Este backfill los registra como inversionista único
con 100% de participación (mismo valor que su titular), preservando el
comportamiento actual. Idempotente: solo inserta donde no existe ya una fila
para ese proyecto.

Revision ID: 038
Revises: 037
Create Date: 2026-07-07
"""
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO proyecto_inversionistas (proyecto_id, cliente_id, porcentaje_participacion, es_patrimonio_autonomo)
        SELECT p.id, p.cliente_id, 1, FALSE
        FROM proyectos p
        WHERE p.cliente_id IS NOT NULL
          AND p.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM proyecto_inversionistas pi WHERE pi.proyecto_id = p.id
          )
    """)


def downgrade() -> None:
    # No se puede distinguir de forma segura una fila sembrada por este backfill
    # de una creada manualmente después con el mismo cliente_id al 100% -- no
    # se revierte automáticamente. Si hace falta, borrar a mano por proyecto_id.
    pass
