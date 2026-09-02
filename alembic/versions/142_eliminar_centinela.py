"""Eliminar fallas.centinela

Auditoria del dominio Fallas 2026-09-02: `centinela` lo creo Laura
(commit 5bf4b29, 2026-04-28) con un proposito -- "quien es la persona
responsable de seguirle la pista a esta falla", con default al nombre del
usuario logueado (ver el adapter legacy de monitoreo de ese mismo commit).
Ese proposito se perdio: no hay ningun campo editable en el formulario
actual para escribirlo, y solo se mostraba como texto crudo en un lugar
del frontend, sin ninguna accion asociada.

Se le agrego despues, sin ningun commit que formalizara el cambio, un
segundo uso informal como "origen automatico" (`MGS_AUTO` para el motor
MGS interno, `API_TEST` para integradores externos, documentado en
docs/API_FALLAS.md) -- pero al ser texto libre sin validacion, un
integrador externo real termino usando el mismo valor `MGS_AUTO` sin ser
el motor interno (ver auditoria de `pendiente_reclasificar` el mismo
dia), asi que tampoco cumplia bien ese segundo proposito. La senal
confiable para "esto lo creo el motor MGS interno" ya es
`alarma_monitoreo_id` (no se puede falsificar, es el que se usa ahora en
el filtro de pendientes reales).

Confirmado con Laura antes de aplicar este cambio (2026-09-02).

Revision ID: 142
Revises: 141
Create Date: 2026-09-02
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if columna_existe(bind, "fallas", "centinela"):
        op.drop_column("fallas", "centinela")


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    if not columna_existe(bind, "fallas", "centinela"):
        op.add_column("fallas", sa.Column("centinela", sa.String(200), nullable=True))
