"""proyecto_info_tecnica: tipo_tracker a Enum, tiene_internet a Boolean

Auditoria de integridad de Proyectos (2026-08-27). Ninguno de los dos
campos tenia proteccion real en la base de datos pese a que ya eran
texto libre acotado en la práctica:

- tipo_tracker: solo '1P' (15) y '2P' (9) se han usado jamás (86 NULL).
  El frontend ya restringía la edición con un Select(['1P','2P']), pero
  la columna en sí aceptaba cualquier VARCHAR(10) -- por API directa o
  por un futuro descuido en el frontend no había ninguna barrera real.
- tiene_internet: solo 'Sí' se ha registrado jamás (96 NULL, 0 'No').
  Es semánticamente un booleano tri-estado (Sí / No / sin dato) y no
  texto libre -- pasa a BOOLEAN nullable.

Migracion de solo-tipo, sin backfill de datos nuevos: los valores
actuales ya son compatibles 1:1 con el tipo destino.

Revision ID: 114
Revises: 113
Create Date: 2026-08-27
"""
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None

_TIPO_TRACKER = postgresql.ENUM("1P", "2P", name="tipo_tracker_enum")


def upgrade():
    bind = op.get_bind()
    _TIPO_TRACKER.create(bind, checkfirst=True)

    op.execute(
        "ALTER TABLE proyecto_info_tecnica ALTER COLUMN tipo_tracker "
        "TYPE tipo_tracker_enum USING tipo_tracker::tipo_tracker_enum"
    )
    op.execute(
        "ALTER TABLE proyecto_info_tecnica ALTER COLUMN tiene_internet "
        "TYPE BOOLEAN USING (tiene_internet = 'Sí')"
    )


def downgrade():
    op.execute(
        "ALTER TABLE proyecto_info_tecnica ALTER COLUMN tipo_tracker "
        "TYPE VARCHAR(10) USING tipo_tracker::text"
    )
    op.execute(
        "ALTER TABLE proyecto_info_tecnica ALTER COLUMN tiene_internet "
        "TYPE VARCHAR(10) USING (CASE WHEN tiene_internet THEN 'Sí' WHEN NOT tiene_internet THEN 'No' ELSE NULL END)"
    )

    bind = op.get_bind()
    _TIPO_TRACKER.drop(bind, checkfirst=True)
