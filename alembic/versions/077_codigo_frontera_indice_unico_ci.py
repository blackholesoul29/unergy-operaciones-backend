"""fronteras.codigo_frontera -- indice unico case-insensitive que ignora borradas

Reemplaza la restriccion UNIQUE(codigo_frontera) (sensible a mayusculas, no
distingue filas borradas) por un indice unico parcial sobre lower(codigo_frontera)
que solo aplica a fronteras vivas (deleted_at IS NULL).

Motivo (diagnostico de Fronteras, Sara, 2026-08-24):
- Una frontera borrada quedaba con su codigo "atrapado" para siempre: un
  POST /fronteras o una confirmacion desde Quoia con el mismo codigo
  chocaba contra el UNIQUE viejo (o, peor, actualizaba la fila borrada sin
  levantarle deleted_at, dejandola invisible pese a un 201 "exito").
- confirmar_frontera_quoia ya comparaba case-insensitive (func.lower) pero
  POST /fronteras comparaba exacto -- un mismo codigo con distinta
  mayuscula podia crear dos filas para el mismo punto fisico, ya que el
  UNIQUE de Postgres tambien era sensible a mayusculas.

Verificado antes de esta migracion: 0 codigos duplicados case-insensitive
entre fronteras vivas, y 0 en total (incluyendo borradas) -- se puede crear
el indice sin resolver datos primero.

Revision ID: 077
Revises: 076
Create Date: 2026-08-24
"""
from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("fronteras_codigo_frontera_key", "fronteras", type_="unique")
    op.execute("""
        CREATE UNIQUE INDEX ix_fronteras_codigo_frontera_unico
        ON fronteras (lower(codigo_frontera))
        WHERE deleted_at IS NULL AND codigo_frontera IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_fronteras_codigo_frontera_unico")
    op.create_unique_constraint("fronteras_codigo_frontera_key", "fronteras", ["codigo_frontera"])
