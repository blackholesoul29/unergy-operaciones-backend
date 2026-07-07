"""Quitar 'soporte' y 'monitoreo' de tipo_contacto_enum -- sin uso real en
la UI ni en los flujos de notificacion. Las alarmas MGS, que usaban
'monitoreo', pasan a resolver con 'operacional' (ver
app/services/mgs/scheduler.py).

Postgres no soporta DROP VALUE en un tipo ENUM, asi que se recrea el tipo:
1) reasignar filas existentes de soporte/monitoreo a operacional (evitando
   violar los UNIQUE si ya existe una fila operacional equivalente -- en ese
   caso se descarta el duplicado, no se pierde el operacional existente),
2) crear el enum nuevo sin esos valores y migrar las columnas,
3) reemplazar el tipo viejo por el nuevo.

Revision ID: 039
Revises: 038
Create Date: 2026-07-08
"""
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def _reasignar_a_operacional(tabla: str, columnas_unicas: str) -> None:
    op.execute(f"""
        UPDATE {tabla}
        SET tipo = 'operacional'
        WHERE tipo IN ('soporte', 'monitoreo')
          AND NOT EXISTS (
              SELECT 1 FROM {tabla} t2
              WHERE t2.tipo = 'operacional' AND {columnas_unicas}
          )
    """)
    op.execute(f"DELETE FROM {tabla} WHERE tipo IN ('soporte', 'monitoreo')")


def upgrade() -> None:
    _reasignar_a_operacional(
        "contactos", "t2.cliente_id = contactos.cliente_id AND t2.email = contactos.email"
    )
    _reasignar_a_operacional(
        "proyecto_area_contacto", "t2.proyecto_id = proyecto_area_contacto.proyecto_id"
    )

    op.execute("CREATE TYPE tipo_contacto_enum_new AS ENUM ('operacional', 'cgm', 'liquidacion')")
    op.execute("ALTER TABLE contactos ALTER COLUMN tipo TYPE tipo_contacto_enum_new USING tipo::text::tipo_contacto_enum_new")
    op.execute("ALTER TABLE proyecto_area_contacto ALTER COLUMN tipo TYPE tipo_contacto_enum_new USING tipo::text::tipo_contacto_enum_new")
    op.execute("DROP TYPE tipo_contacto_enum")
    op.execute("ALTER TYPE tipo_contacto_enum_new RENAME TO tipo_contacto_enum")


def downgrade() -> None:
    op.execute("ALTER TYPE tipo_contacto_enum ADD VALUE IF NOT EXISTS 'soporte'")
    op.execute("ALTER TYPE tipo_contacto_enum ADD VALUE IF NOT EXISTS 'monitoreo'")
