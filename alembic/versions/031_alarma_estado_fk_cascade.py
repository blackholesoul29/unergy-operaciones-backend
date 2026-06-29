"""Add ON DELETE CASCADE to alarma_estado.proyecto_id

La tabla `alarma_estado` se creó (DDL idempotente en `app/main.py`) con
`proyecto_id BIGINT NOT NULL` SIN clave foránea, por lo que al borrar un
proyecto quedaban filas de estado de alarma huérfanas. Esta migración agrega
la FK hacia `proyectos(id)` con `ON DELETE CASCADE` para mantener la
consistencia, igual que el resto de tablas con `proyecto_id`.

Idempotente: borra primero filas huérfanas (las que el cascade habría
eliminado) para que el ADD CONSTRAINT no falle, y usa nombre de constraint
explícito para poder recrearlo/eliminarlo sin sorpresas.

Revision ID: 031
Revises: 030
Create Date: 2026-06-29
"""
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

_CONSTRAINT = "fk_alarma_estado_proyecto_id"


def upgrade() -> None:
    # Limpia filas huérfanas antes de imponer la FK (de lo contrario el
    # ADD CONSTRAINT falla con foreign_key_violation).
    op.execute(
        "DELETE FROM alarma_estado WHERE proyecto_id NOT IN (SELECT id FROM proyectos)"
    )
    # Reemplaza la constraint si por algún motivo ya existiera (idempotencia).
    op.execute(f"ALTER TABLE alarma_estado DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE alarma_estado ADD CONSTRAINT {_CONSTRAINT} "
        "FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE alarma_estado DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
