"""Generación mensual promedio por proyecto, persistida en BD.

Evita que cada vista de contratos tenga que salir a la API de generación de
Unergy: el promedio se calcula una vez (app/services/gen_promedio.py) y queda
guardado. Las plantas sin histórico se cargan a mano, por eso se guarda también
el origen del dato.

Todo nullable y aditivo: ninguna fila existente cambia.

Revision ID: 058
Revises: 057
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa
from alembic_idempotencia import agregar_columna_si_falta

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


COLUMNAS = [
    ("gen_mensual_promedio_mwh", sa.Numeric(12, 3)),
    ("gen_promedio_origen", sa.String(10)),          # 'api' | 'manual'
    ("gen_promedio_meses", sa.Integer()),
    ("gen_promedio_desde", sa.Date()),
    ("gen_promedio_hasta", sa.Date()),
    ("gen_promedio_actualizado_en", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    bind = op.get_bind()
    for nombre, tipo in COLUMNAS:
        agregar_columna_si_falta(bind, "proyectos", sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    for nombre, _ in reversed(COLUMNAS):
        op.drop_column("proyectos", nombre)
