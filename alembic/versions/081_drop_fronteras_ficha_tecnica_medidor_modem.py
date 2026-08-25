"""fronteras: eliminar ficha tecnica medidor/modem (tipo_extraccion,
password_medidor, ip_modem, puerto_modem, canal_comunicacion x ppal/resp)

Sara, 2026-08-25: estos 10 campos se agregaron 2026-08-14 (commit
f5e0881) con la idea de capturar la ficha tecnica de conexion de cada
medidor/modem, pero nunca se conecto ninguna fuente -- ni automatica
(confirmado: ningun endpoint de Quoia/Gaia devuelve IP, puerto, canal de
comunicacion, protocolo de extraccion ni password de medidor) ni manual
(0/145 fronteras con dato en produccion). Sara decidio eliminarlos en vez
de dejarlos como ruido sin completar.

Revision ID: 081
Revises: 080
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None

_COLUMNAS = [
    ("tipo_extraccion_ppal", sa.String(50)),
    ("password_medidor_ppal", sa.String(100)),
    ("ip_modem_ppal", sa.String(50)),
    ("puerto_modem_ppal", sa.Integer()),
    ("canal_comunicacion_ppal", sa.String(50)),
    ("tipo_extraccion_resp", sa.String(50)),
    ("password_medidor_resp", sa.String(100)),
    ("ip_modem_resp", sa.String(50)),
    ("puerto_modem_resp", sa.Integer()),
    ("canal_comunicacion_resp", sa.String(50)),
]


def upgrade():
    for nombre, _ in _COLUMNAS:
        op.drop_column("fronteras", nombre)


def downgrade():
    for nombre, tipo in _COLUMNAS:
        op.add_column("fronteras", sa.Column(nombre, tipo, nullable=True))
