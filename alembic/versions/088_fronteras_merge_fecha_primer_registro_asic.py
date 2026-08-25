"""fronteras: fusionar fecha_primer_registro_asic en fecha_registro_asic

Auditoria de calidad de datos de Fronteras (2026-08-25): fecha_registro_asic
es la fecha de registro VIGENTE (se alimenta en vivo desde Quoia al
confirmar una frontera + backfill_fecha_registro_asic, sigue activa).
fecha_primer_registro_asic era la fecha del PRIMER registro historico,
poblada solo por el script cargar_fronteras_gescon.py (ya retirado,
commit d0fad40) desde un Excel externo -- desde entonces es un dato
congelado que nadie vuelve a escribir.

Sara decidio: fecha_registro_asic es la mas confiable y mantenible.
Antes de eliminar fecha_primer_registro_asic, se rellenan con su valor
las filas donde fecha_registro_asic esta en NULL (3 en produccion:
ids 1, 2 y 51) para no perder ese dato -- las demas 91 filas pobladas
de fecha_primer_registro_asic ya tenian fecha_registro_asic con dato
propio, asi que se descartan sin backfill (es la fecha VIGENTE la que
se conserva, no la primera).

Revision ID: 088
Revises: 087
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE fronteras SET fecha_registro_asic = fecha_primer_registro_asic "
        "WHERE fecha_registro_asic IS NULL AND fecha_primer_registro_asic IS NOT NULL"
    )
    op.drop_column("fronteras", "fecha_primer_registro_asic")


def downgrade():
    # No se puede reconstruir el valor original de fecha_primer_registro_asic
    # para las filas donde ya tenia un valor distinto al vigente -- ese dato
    # se fusiono a proposito. El downgrade solo restaura la forma de la
    # columna, no el contenido.
    op.add_column("fronteras", sa.Column("fecha_primer_registro_asic", sa.Date(), nullable=True))
