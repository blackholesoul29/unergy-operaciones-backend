"""gmail_credenciales -- borrar la tabla zombie que revivia en cada deploy

Fase 0 del refactor del nucleo (docs/refactor/06-plan-migracion.md, paso 0.4).

La migracion 032 (2026-07-02) borro esta tabla junto a otras 9 huerfanas
"confirmadas en 0 filas", pero el bloque _PENDING_DDLS de app/main.py seguia
teniendo su CREATE TABLE IF NOT EXISTS, y ese DDL si corre en cada arranque.
Resultado: la tabla volvia a aparecer en produccion, vacia, sin modelo ORM y
sin nadie que la lea. Es el hallazgo F2 de esquema-bd-produccion/DEPURACION.md.

El CREATE ya se quito de _PENDING_DDLS en el mismo commit que esta revision,
asi que ahora el DROP si es definitivo.

No lleva downgrade real: recrear una tabla vacia que nadie usa no aporta nada,
y volver a crearla seria justamente el bug que estamos cerrando.

Revision ID: 101
Revises: 100
Create Date: 2026-08-25
"""
from alembic import op

from alembic_idempotencia import tabla_existe

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotente a proposito: create_all y _PENDING_DDLS corren ANTES que
    # Alembic, y un fallo aca haria rollback de toda la cadena de migraciones
    # (ver el docstring de alembic_idempotencia.py).
    bind = op.get_bind()
    if tabla_existe(bind, "gmail_credenciales"):
        op.execute("DROP TABLE gmail_credenciales")


def downgrade():
    # Deliberadamente vacio: ver el docstring.
    pass
