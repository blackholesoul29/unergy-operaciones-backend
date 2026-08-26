"""reporte_energia_generacion: agrega curva_respaldo_final + respaldo_final_origen

Pedido de Sara (2026-08-25): hasta ahora, cuando /enviar mandaba una fila a
Quoia, el "Backup" SIEMPRE se calculaba como una estimación ±1% sobre
curva_final (o el dato real de FRONTERAS_TERCEROS, si existía) -- aunque
para fronteras normales ya tuviéramos el dato REAL del medidor de respaldo
guardado en curva_medidor_respaldo, y fuera válido.

Ahora curva_respaldo_a_reportar() (utils.py) usa el dato real del medidor
de respaldo cuando: curva_final vino del medidor principal, ambos medidores
quedaron completos ese día, y el respaldo está a 1.5 kWh o menos (la peor
de las 24 horas) de diferencia del principal -- umbral confirmado con el
equipo de campo y contrastado contra el histórico real (ver commit).

Se persiste en vez de recalcularse en cada consulta -- mismo motivo que
curva_medidor_principal/respaldo: la fórmula ±1% usa random.uniform(), así
que sin persistir, el preview que ve el frontend podría no coincidir con lo
que realmente se envió a Quoia.

Revision ID: 099
Revises: 098
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("reporte_energia_generacion")}
    if "curva_respaldo_final" not in existing:
        op.add_column("reporte_energia_generacion", sa.Column("curva_respaldo_final", sa.dialects.postgresql.JSONB(), nullable=True))
    if "respaldo_final_origen" not in existing:
        op.add_column("reporte_energia_generacion", sa.Column("respaldo_final_origen", sa.String(20), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("reporte_energia_generacion")}
    if "respaldo_final_origen" in existing:
        op.drop_column("reporte_energia_generacion", "respaldo_final_origen")
    if "curva_respaldo_final" in existing:
        op.drop_column("reporte_energia_generacion", "curva_respaldo_final")
