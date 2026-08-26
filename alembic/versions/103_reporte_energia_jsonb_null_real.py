"""reporte_energia_generacion/consumo: backfill 'null' JSON -> SQL NULL real

Las columnas JSONB de estas dos tablas se creaban sin none_as_null=True --
SQLAlchemy serializaba un Python None como el LITERAL JSON 'null' (una fila
CON dato, no SQL NULL) en vez de columna NULL de verdad. No rompia el ORM
(json.loads('null') sigue dando None de vuelta), pero es una trampa para
cualquier query SQL/BI directa que filtre con IS NULL/IS NOT NULL --
verificado en produccion: ~1298 filas de horas_rellenadas_reconectador
salian "IS NOT NULL" cuando solo 13 tenian dato real (auditoria Reporte
ASIC 2026-08-26). El modelo ya se corrigio (JSONB(none_as_null=True)) para
que las escrituras NUEVAS queden bien -- esta migracion arregla las filas
YA escritas asi.

Idempotente: el UPDATE con WHERE col = 'null'::jsonb no encuentra nada la
segunda vez que corre.

Revision ID: 103
Revises: 102
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None

COLUMNAS_POR_TABLA = {
    "reporte_energia_generacion": [
        "curva_final", "curva_respaldo_terceros", "curva_respaldo_final",
        "curva_medidor_principal", "curva_medidor_respaldo", "curva_solenium_referencia",
        "curva_reconectador_referencia", "horas_rellenadas_reconectador",
        "horas_rellenadas_solenium", "horas_rellenadas_historico",
        "horas_rellenadas_medidor_cruzado",
    ],
    "reporte_energia_consumo": [
        "curva_final", "curva_medidor_principal", "curva_medidor_respaldo",
        "curva_respaldo_final", "horas_rellenadas_historico", "horas_rellenadas_medidor_cruzado",
    ],
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tablas_existentes = set(inspector.get_table_names())
    for tabla, columnas in COLUMNAS_POR_TABLA.items():
        if tabla not in tablas_existentes:
            continue
        columnas_reales = {c["name"] for c in inspector.get_columns(tabla)}
        for col in columnas:
            if col not in columnas_reales:
                continue
            op.execute(sa.text(f'UPDATE {tabla} SET "{col}" = NULL WHERE "{col}" = \'null\'::jsonb'))


def downgrade():
    # No hay vuelta atrás real -- SQL NULL y JSON 'null' se leen igual desde
    # el ORM (json.loads('null') -> None), así que no hay ningún dato que
    # "restaurar". Downgrade no-op a propósito.
    pass
