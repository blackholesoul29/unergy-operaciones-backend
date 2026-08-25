"""drop proyectos.proyecto_padre_id (self-ref padre-hijo, sin disparador real)

Decidido con el usuario (Sara) 2026-08-20. En la migracion 070 se habia
decidido mantener este campo porque `merge_proyectos` lo maneja (repunta
los hijos de un proyecto fusionado hacia el ganador). Al revisar en detalle
se confirmo que ese repunte es codigo puramente defensivo: nada en toda la
plataforma crea el vinculo padre-hijo inicial (ni frontend, ni ningun otro
servicio backend) -- la unica via era un PATCH crudo a la API, nunca usada.
0 proyectos con el campo poblado hoy, y ninguna fusion realizada hasta ahora
(incluida Astrea 1/2) llego a ejercitar ese bloque.

Se evaluo construir un selector real en el frontend para activarlo, pero
sin un caso de uso concreto se prefirio eliminar el campo en vez de dejar
codigo especulativo esperando un escenario que nunca se puede producir.

Se elimina junto con este campo:
- La relationship ORM `Proyecto.subproyectos` (invisible en API/frontend).
- El bloque de repunte self-ref dentro de `merge_proyectos`
  (app/api/v1/proyectos.py).
- Su uso en el check de `business_records` que bloquea el DELETE de un
  proyecto (`p.subproyectos`), y en la ficha de identificacion de
  comercial.py.

Revision ID: 071
Revises: 070
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade():
    # La migracion 007 declaraba un indice "ix_proyectos_proyecto_padre_id" que
    # nunca llego a existir en produccion (solo quedo el FK constraint) -- no se
    # intenta borrar un indice que no esta. drop_column se lleva el FK con el.
    op.drop_column("proyectos", "proyecto_padre_id")


def downgrade():
    op.add_column(
        "proyectos",
        sa.Column("proyecto_padre_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=True),
    )
