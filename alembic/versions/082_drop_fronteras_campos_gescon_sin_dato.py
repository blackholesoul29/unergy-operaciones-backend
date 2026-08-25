"""fronteras: eliminar 12 campos de GESCON en 0/145 poblados + 2 columnas
huerfanas (agrupada_bajo/embebida_bajo, nunca declaradas en el modelo)

Sara, 2026-08-25: auditoria completa de poblacion de los ~95 campos de
`fronteras` contra produccion (145 fronteras activas). Estos 12 campos
nunca tuvieron dato real y ninguno se lee en codigo (confirmado por grep
en app/, distinto de subestacion/punto_conexion/niu, que SI se leen en
`_fronteras_planta` de comercial.py pese a estar en 0% -- esos se dejan
intactos a proposito).

De paso se eliminan `agrupada_bajo`/`embebida_bajo` (sin `_id`): columnas
que existen fisicamente en la tabla de produccion pero que NUNCA
estuvieron declaradas en el modelo de SQLAlchemy -- probablemente el
intento original de acomodar el texto libre que mandaba
scripts/cargar_fronteras_gescon.py (ya eliminado) antes de que el
diseño pasara a `agrupada_bajo_id`/`embebida_bajo_id` (esas dos SI
estaban en el modelo y ya se eliminaron en la migracion 080). Deriva de
esquema pura, 0/145 pobladas, cero referencias en el codigo.

Revision ID: 082
Revises: 081
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None

_COLUMNAS = [
    ("capacidad_transporte_compartida_mw", sa.Numeric(10, 4)),
    ("nit", sa.String(20)),
    ("nit_rf", sa.String(20)),
    ("nit_cgm", sa.String(20)),
    ("predio_id", sa.String(50)),
    ("nombre_predio", sa.String(255)),
    ("representante_ddv", sa.String(255)),
    ("consumo_promedio_mensual_mwh", sa.Numeric(12, 3)),
    ("relacion_transformacion_ct", sa.String(100)),
    ("relacion_transformacion_pt", sa.String(100)),
    ("codigo_sic_ddv", sa.String(50)),
    ("codigo_sic_submercado_usuario", sa.String(20)),
]

_COLUMNAS_HUERFANAS = [
    ("agrupada_bajo", sa.String(50)),
    ("embebida_bajo", sa.String(50)),
]


def upgrade():
    for nombre, _ in _COLUMNAS:
        op.drop_column("fronteras", nombre)
    for nombre, _ in _COLUMNAS_HUERFANAS:
        op.execute(f"ALTER TABLE fronteras DROP COLUMN IF EXISTS {nombre}")


def downgrade():
    for nombre, tipo in _COLUMNAS:
        op.add_column("fronteras", sa.Column(nombre, tipo, nullable=True))
    # Las huerfanas no se recrean: nunca estuvieron en el modelo, no hay
    # tipo real que restaurar con certeza.
