"""FK real de fallas.alarma_monitoreo_id -> alarmas_monitoreo.id

Auditoria del dominio Fallas 2026-09-02: `Falla.alarma_monitoreo_id`
(app/models/fallas.py) nunca tuvo una FK real -- es un BigInteger suelto
con indice, sin restriccion hacia `alarmas_monitoreo.id` (esa tabla no
tiene modelo ORM, ver migracion 135). La BD no impedia que apuntara a un
id inexistente.

Esto importa mas desde el fix del emparejamiento alarma-falla (commit
d28eb27, mismo dia): _auto_create_fallas/_auto_close_fallas ahora confian
en `alarma_monitoreo_id` (via join a alarmas_monitoreo.alarm_type) como la
fuente de verdad para decidir a que alarma pertenece una falla, en vez del
texto de `descripcion`. Sin la FK, nada impide que ese campo termine
apuntando a un id que no existe.

Verificado contra el snapshot de Railway antes de escribir esto: 0 fallas
con alarma_monitoreo_id no nulo tenian una alarmas_monitoreo huerfana --
pero se limpia de todas formas por si la BD real de produccion tiene
alguna, para que el ADD CONSTRAINT no falle.

Revision ID: 138
Revises: 137
Create Date: 2026-09-02
"""
from alembic import op
from sqlalchemy import text

from alembic_idempotencia import constraint_existe

revision = "138"
down_revision = "137"
branch_labels = None
depends_on = None

_CONSTRAINT = "fk_fallas_alarma_monitoreo_id"


def upgrade() -> None:
    bind = op.get_bind()
    if constraint_existe(bind, "fallas", _CONSTRAINT):
        return

    # Defensivo: limpiar referencias huerfanas antes de poder agregar la FK
    # (ADD CONSTRAINT falla si alguna fila viola la restriccion).
    bind.execute(text("""
        UPDATE fallas SET alarma_monitoreo_id = NULL
        WHERE alarma_monitoreo_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM alarmas_monitoreo am WHERE am.id = fallas.alarma_monitoreo_id
          )
    """))

    op.create_foreign_key(
        _CONSTRAINT, "fallas", "alarmas_monitoreo",
        ["alarma_monitoreo_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if constraint_existe(bind, "fallas", _CONSTRAINT):
        op.drop_constraint(_CONSTRAINT, "fallas", type_="foreignkey")
