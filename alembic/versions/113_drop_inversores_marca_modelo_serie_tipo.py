"""proyecto_inversores: eliminar marca/modelo/numero_serie/tipo

Ninguna vista de la plataforma lee o escribe estos 4 campos -- ni el
selector de "que inversor fallo" (FallaForm.vue/FallaCreateSheet.vue),
ni InformeOMView.vue, ni ninguna otra. marca/modelo/numero_serie:
0/675 filas pobladas nunca. `tipo`: 670/675 pobladas, pero es un valor
sintetico ("central") que ponia el propio backfill automatico al
sembrar la config tipica de minigranja -- no una dato real cargado por
alguien; ese backfill se elimina en este mismo cambio (era ademas la
fuente de la condicion de carrera que motivo la migracion 112).

Revision ID: 113
Revises: 112
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for col in ("marca", "modelo", "numero_serie", "tipo"):
        if columna_existe(bind, "proyecto_inversores", col):
            op.execute(f"ALTER TABLE proyecto_inversores DROP COLUMN {col}")
    op.execute("DROP TYPE IF EXISTS tipo_inversor_enum")


def downgrade():
    # 0% de adopcion real (marca/modelo/numero_serie) o solo un valor
    # sintetico del backfill ya eliminado (tipo): no hay nada que recrear.
    pass
