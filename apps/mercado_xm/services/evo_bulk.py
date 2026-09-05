"""Carga masiva de índices climáticos e histórico de precios (endpoint admin).

Las tres tablas se llenan con el mismo patrón: upsert por su clave natural.
Se hace en UNA transacción: una carga a medias dejaría meses sueltos y el
siguiente análisis de correlación saldría mal sin avisar.
"""

from django.db import connection, transaction

_SQL = {
    "oni": """
        INSERT INTO clima_oni_monthly
            (year, month, oni_value, soi_value, pdo_value, mjo_amplitude,
             enso_phase)
        VALUES (%(year)s, %(month)s, %(oni)s, %(soi)s, %(pdo)s, %(mjo)s,
                %(phase)s)
        ON CONFLICT (year, month) DO UPDATE SET
            oni_value = EXCLUDED.oni_value,
            soi_value = EXCLUDED.soi_value,
            pdo_value = EXCLUDED.pdo_value,
            mjo_amplitude = EXCLUDED.mjo_amplitude,
            enso_phase = EXCLUDED.enso_phase
    """,
    "precip": """
        INSERT INTO clima_precip_monthly
            (year, month, region, precip_mm, anomaly_pct, climatology_mm)
        VALUES (%(year)s, %(month)s, %(region)s, %(precip_mm)s,
                %(anomaly_pct)s, %(climatology_mm)s)
        ON CONFLICT (year, month, region) DO UPDATE SET
            precip_mm = EXCLUDED.precip_mm,
            anomaly_pct = EXCLUDED.anomaly_pct,
            climatology_mm = EXCLUDED.climatology_mm
    """,
    "prices": """
        INSERT INTO clima_price_monthly
            (year, month, price_cop_kwh, enso_phase, precip_andina_mm)
        VALUES (%(year)s, %(month)s, %(price_cop_kwh)s, %(enso_phase)s,
                %(precip_andina_mm)s)
        ON CONFLICT (year, month) DO UPDATE SET
            price_cop_kwh = EXCLUDED.price_cop_kwh,
            enso_phase = EXCLUDED.enso_phase,
            precip_andina_mm = EXCLUDED.precip_andina_mm
    """,
}


@transaction.atomic
def cargar(payload: dict) -> dict[str, int]:
    """Devuelve cuántas filas se cargaron de cada tipo."""
    cargados = {clave: 0 for clave in _SQL}
    with connection.cursor() as cursor:
        for clave, sql in _SQL.items():
            for fila in payload.get(clave, []):
                cursor.execute(sql, fila)
                cargados[clave] += 1
    return cargados
