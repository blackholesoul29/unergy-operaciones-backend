"""Eliminar fallas.asignado_a_id

Auditoria del dominio Fallas 2026-09-02: `asignado_a_id` existia desde el
commit inicial del backend (24-abr-2026) para registrar quien es el
responsable de resolver la falla, distinto de quien la registro
(`registrado_por_id`). Estaba completamente construido -- FK a usuarios,
`FallaCreate`/`FallaUpdate` lo aceptaban, notificacion in-app automatica al
reasignar, selectores y filtro por asignado en el frontend, y una vista
mobile dedicada (`MobileTecnicoFallasView.vue`) para que un tecnico viera
"mis fallas asignadas".

Nunca se adopto en la operacion real: de 6444 fallas activas, solo 3 tienen
el campo poblado, las tres del mismo dia (10-jun-2026), asignadas por Laura
y Juanjo a modo de prueba. El roster de usuarios no tiene tecnicos/
coordinadores reales -- las dos unicas cuentas con esos roles
(`Intento 1 coordiandor`, `inetonto 2 tecnico`) son cuentas de prueba de la
propia Laura, quien en la practica gestiona todas las fallas directamente.

Decision de negocio (2026-09-02): eliminar el campo y la logica que depende
al 100% de el (notificacion de reasignacion, selectores/filtro en frontend,
la vista mobile de tecnico). El rol tecnico/coordinador y la vista general
de gestion de fallas mobile (`MobileCoordinadorFallasView.vue`) se
conservan -- no forman parte de este cambio.

Revision ID: 143
Revises: 142
Create Date: 2026-09-02
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "143"
down_revision = "142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if columna_existe(bind, "fallas", "asignado_a_id"):
        op.drop_column("fallas", "asignado_a_id")


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    if not columna_existe(bind, "fallas", "asignado_a_id"):
        op.add_column("fallas", sa.Column("asignado_a_id", sa.BigInteger(),
                                           sa.ForeignKey("usuarios.id"), nullable=True))
