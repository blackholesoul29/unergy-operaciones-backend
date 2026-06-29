"""Add ON DELETE CASCADE to alarma_estado.proyecto_id

La tabla `alarma_estado` se creó (DDL idempotente en `app/main.py`) con
`proyecto_id BIGINT NOT NULL` SIN clave foránea, por lo que al borrar un
proyecto quedaban filas de estado de alarma huérfanas. Esta migración agrega
la FK hacia `proyectos(id)` con `ON DELETE CASCADE` para mantener la
consistencia, igual que el resto de tablas con `proyecto_id`.

Idempotente: borra primero filas huérfanas (las que el cascade habría
eliminado) para que el ADD CONSTRAINT no falle, y usa nombre de constraint
explícito para poder recrearlo/eliminarlo sin sorpresas.

IMPORTANTE — orden de arranque (start.sh): `init_db.py` (create_all + seed) →
`alembic upgrade head` → uvicorn (lifespan crea `alarma_estado` vía
`_PENDING_DDLS`). La tabla `alarma_estado` NO tiene modelo SQLAlchemy ni la crea
ninguna migración: nace del DDL de arranque, que corre DESPUÉS de Alembic. En
una BD nueva la tabla aún no existe cuando corre esta migración, así que el
ALTER/DELETE fallaría ("relation alarma_estado does not exist") y dejaría
Alembic atascado bajo head. Por eso `upgrade()` salta si la tabla no existe: el
DDL de arranque la creará YA con la FK (ver `app/main.py`). En prod existente la
tabla ya existe y la migración impone la FK normalmente.

Revision ID: 031
Revises: 030
Create Date: 2026-06-29
"""
from alembic import op
from sqlalchemy import text

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

_CONSTRAINT = "fk_alarma_estado_proyecto_id"


def upgrade() -> None:
    # `alarma_estado` la crea el DDL de arranque (lifespan), que corre DESPUÉS
    # de Alembic. En una BD nueva la tabla aún no existe: saltamos y dejamos que
    # ese DDL la cree con la FK ya incluida. Sin esta guarda el ALTER fallaría y
    # dejaría Alembic atascado en 030 hasta un segundo arranque.
    bind = op.get_bind()
    if bind.execute(text("SELECT to_regclass('public.alarma_estado')")).scalar() is None:
        return
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
    # Misma guarda: si la tabla no existe, `DROP CONSTRAINT IF EXISTS` igual
    # falla con "relation does not exist". Nada que revertir en ese caso.
    bind = op.get_bind()
    if bind.execute(text("SELECT to_regclass('public.alarma_estado')")).scalar() is None:
        return
    op.execute(f"ALTER TABLE alarma_estado DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
