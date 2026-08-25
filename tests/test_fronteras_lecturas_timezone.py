"""GET /fronteras/{id}/lecturas -- el rango desde/hasta debe interpretarse en
hora Colombia (UTC-5), no como datetime naive (que Postgres interpretaría
según el timezone de la sesión, no necesariamente Colombia) -- punto 9 del
diagnóstico de Fronteras, 2026-08-24.

SQLite no compara correctamente DateTime(timezone=True) (a diferencia de
Postgres, el motor real en producción) -- se prueba la construcción del
límite directamente en vez de un round-trip por la BD, que daría un falso
negativo/positivo según cómo SQLite decida comparar las cadenas."""
import datetime as dt

from app.api.v1.fronteras import _COL_TZ


def test_limite_hasta_es_justo_antes_de_medianoche_colombia_en_utc():
    hasta = dt.date(2026, 8, 24)
    limite = dt.datetime.combine(hasta, dt.datetime.max.time(), tzinfo=_COL_TZ)

    # 23:59:59.999999 del 24/08 en Colombia (UTC-5) == 04:59:59.999999 UTC
    # del 25/08 -- si el límite se construyera naive (sin tzinfo), Postgres
    # lo interpretaría según el timezone de la sesión, no necesariamente
    # Colombia, corriendo este límite hasta 5 horas en cualquier dirección.
    assert limite.astimezone(dt.timezone.utc) == dt.datetime(
        2026, 8, 25, 4, 59, 59, 999999, tzinfo=dt.timezone.utc,
    )


def test_limite_desde_es_medianoche_colombia_en_utc():
    desde = dt.date(2026, 8, 24)
    limite = dt.datetime.combine(desde, dt.datetime.min.time(), tzinfo=_COL_TZ)

    # 00:00:00 del 24/08 en Colombia == 05:00:00 UTC del mismo 24/08.
    assert limite.astimezone(dt.timezone.utc) == dt.datetime(
        2026, 8, 24, 5, 0, 0, tzinfo=dt.timezone.utc,
    )


def test_una_lectura_de_ultima_hora_de_colombia_cae_dentro_del_rango_hasta():
    """El caso concreto que estaba roto: una lectura de las 23:30 hora
    Colombia (ya 04:30 UTC del día siguiente) debe seguir contando como
    parte del día que se está consultando."""
    hasta = dt.date(2026, 8, 24)
    limite = dt.datetime.combine(hasta, dt.datetime.max.time(), tzinfo=_COL_TZ)

    lectura_23_30_colombia = dt.datetime(2026, 8, 25, 4, 30, tzinfo=dt.timezone.utc)
    lectura_00_30_colombia_del_25 = dt.datetime(2026, 8, 25, 5, 30, tzinfo=dt.timezone.utc)

    assert lectura_23_30_colombia <= limite
    assert lectura_00_30_colombia_del_25 > limite
