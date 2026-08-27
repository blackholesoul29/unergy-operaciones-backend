"""proyectos: re-drop nombre_bitacora / nombre_clientes (resucitadas)

Estas dos columnas ya se habían eliminado en la migracion 105
(2026-08-27, ~11:35). init_db.py tenia su propio ADD COLUMN IF NOT
EXISTS para las dos (mecanismo separado de _PENDING_DDLS/Alembic, ver
commit 20e4bdf) que quedo sin corregir hasta ~11:42 ese mismo dia --
en la ventana entre ambos commits, un deploy corrio el init_db.py
todavia viejo y las volvio a crear (vacias; alembic_version nunca se
movio de vuelta, asi que no fue un downgrade). La correccion de
init_db.py evita que vuelva a pasar hacia adelante, pero no limpia lo
que ya habia quedado creado -- esta migracion hace esa limpieza.

Revision ID: 111
Revises: 110
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "proyectos", "nombre_bitacora"):
        op.execute("ALTER TABLE proyectos DROP COLUMN nombre_bitacora")
    if columna_existe(bind, "proyectos", "nombre_clientes"):
        op.execute("ALTER TABLE proyectos DROP COLUMN nombre_clientes")


def downgrade():
    # 0% poblado en ambas corridas (la original y esta resurreccion
    # accidental): no hay nada que recrear.
    pass
