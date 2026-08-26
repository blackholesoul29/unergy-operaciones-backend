"""reporte_energia: elimina validado_por_id/validado_en

Pedido por Sara (2026-08-26), parte de la auditoria de Reporte ASIC/CGM:
estos campos (quien y cuando presiono "Validar" para sacar una fila de
'revisar_manualmente') no aportaban informacion util al ejercicio -- ya
se habian quitado del frontend antes de este cambio (0 referencias en
unergy-operaciones-frontend/src). La accion central del endpoint
POST /validar (`revisar_manualmente = False`) se mantiene intacta; solo
se elimina el rastro de auditoria WHO/WHEN, en ambas tablas
(reporte_energia_generacion y reporte_energia_consumo).

Sin entradas en _PENDING_DDLS (app/main.py) para estos campos -- no
hace falta limpiar el mecanismo legacy.

Idempotente por el mismo motivo que las migraciones recientes de esta
sesion: alembic upgrade head no siempre corre limpio en el deploy de
Railway.

Revision ID: 100
Revises: 099
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None

_TABLAS = ["reporte_energia_generacion", "reporte_energia_consumo"]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for tabla in _TABLAS:
        columnas = {c["name"] for c in inspector.get_columns(tabla)}
        with op.batch_alter_table(tabla) as batch_op:
            if "validado_por_id" in columnas:
                batch_op.drop_column("validado_por_id")
            if "validado_en" in columnas:
                batch_op.drop_column("validado_en")


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for tabla in _TABLAS:
        columnas = {c["name"] for c in inspector.get_columns(tabla)}
        with op.batch_alter_table(tabla) as batch_op:
            if "validado_por_id" not in columnas:
                batch_op.add_column(sa.Column("validado_por_id", sa.BigInteger(), sa.ForeignKey("usuarios.id"), nullable=True))
            if "validado_en" not in columnas:
                batch_op.add_column(sa.Column("validado_en", sa.DateTime(timezone=True), nullable=True))
