"""ReporteEnergiaGeneracion/Consumo -- todas las columnas JSONB deben tener
none_as_null=True.

Sin esto, SQLAlchemy serializa un Python None como el LITERAL JSON 'null'
(una fila CON dato) en vez de columna SQL NULL real -- no rompe el ORM
(json.loads('null') sigue dando None de vuelta), pero es una trampa para
cualquier query SQL/BI directa que filtre con IS NULL/IS NOT NULL
(auditoría Reporte ASIC 2026-08-26). No se puede probar el comportamiento
real contra SQLite (no tiene JSONB) -- esto verifica que el tipo de columna
quedó configurado correctamente, que es lo que de verdad importa contra
Postgres en producción."""
from sqlalchemy.dialects.postgresql import JSONB

from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo


def _columnas_jsonb(modelo):
    return [
        c for c in modelo.__table__.columns
        if isinstance(c.type, JSONB)
    ]


def test_todas_las_columnas_jsonb_de_generacion_tienen_none_as_null():
    columnas = _columnas_jsonb(ReporteEnergiaGeneracion)
    assert len(columnas) >= 11  # las 11 columnas JSONB conocidas de esta tabla
    for c in columnas:
        assert c.type.none_as_null is True, f"{c.name} no tiene none_as_null=True"


def test_todas_las_columnas_jsonb_de_consumo_tienen_none_as_null():
    columnas = _columnas_jsonb(ReporteEnergiaConsumo)
    assert len(columnas) >= 6  # las 6 columnas JSONB conocidas de esta tabla
    for c in columnas:
        assert c.type.none_as_null is True, f"{c.name} no tiene none_as_null=True"
