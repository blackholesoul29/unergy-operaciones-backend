"""Golden tests de cálculos de métricas operativas.

Estos cálculos producen números que ven los operadores; un error aquí es el bug
más caro de la plataforma. Las funciones bajo prueba son puras (sin red/BD).
"""
from datetime import date, datetime, timezone, timedelta

from app.api.v1.cumplimiento import _monthly_mwh_from_records


def _rec(ts: str, gen):
    return {"time_stamp": ts, "generacion": gen}


# ── _monthly_mwh_from_records: contador acumulado → MWh del mes ──────────────

def test_monotonic_counter_equals_last_minus_first():
    """Caso normal: contador monótono. MWh = (último - primero) / 1000."""
    recs = [
        _rec("2026-06-01T06:00:00-05:00", 100_000.0),
        _rec("2026-06-15T12:00:00-05:00", 250_000.0),
        _rec("2026-06-30T18:00:00-05:00", 400_000.0),
    ]
    out = _monthly_mwh_from_records(recs)
    # 400000 - 100000 = 300000 kWh = 300 MWh
    assert out["mwh"] == 300.0
    assert out["n_used"] == 3


def test_unsorted_input_is_sorted_by_timestamp():
    recs = [
        _rec("2026-06-30T18:00:00-05:00", 400_000.0),
        _rec("2026-06-01T06:00:00-05:00", 100_000.0),
        _rec("2026-06-15T12:00:00-05:00", 250_000.0),
    ]
    assert _monthly_mwh_from_records(recs)["mwh"] == 300.0


def test_counter_reset_does_not_corrupt_total():
    """Si el contador se reinicia a mitad de mes, se suman solo deltas positivos.

    Antes (último - primero con heurística) daba un total erróneo; ahora el paso
    negativo del reinicio aporta 0 y se cuenta solo lo realmente producido.
    """
    recs = [
        _rec("2026-06-01T06:00:00-05:00", 900_000.0),
        _rec("2026-06-10T12:00:00-05:00", 1_000_000.0),  # +100000
        _rec("2026-06-11T06:00:00-05:00", 0.0),          # reinicio (delta neg → 0)
        _rec("2026-06-30T18:00:00-05:00", 200_000.0),    # +200000
    ]
    out = _monthly_mwh_from_records(recs)
    # 100000 + 200000 = 300000 kWh = 300 MWh
    assert out["mwh"] == 300.0


def test_null_reading_is_ignored_not_treated_as_zero():
    """Una lectura None NO debe forzarse a 0 (corrompería el delta)."""
    recs = [
        _rec("2026-06-01T06:00:00-05:00", 100_000.0),
        _rec("2026-06-15T12:00:00-05:00", None),       # se ignora
        _rec("2026-06-30T18:00:00-05:00", 250_000.0),
    ]
    out = _monthly_mwh_from_records(recs)
    assert out["mwh"] == 150.0  # 250000 - 100000
    assert out["n_used"] == 2


def test_last_reading_null_uses_real_readings():
    """Lectura de borde nula: antes el mes reportaba 0; ahora usa las reales."""
    recs = [
        _rec("2026-06-01T06:00:00-05:00", 100_000.0),
        _rec("2026-06-29T18:00:00-05:00", 280_000.0),
        _rec("2026-06-30T23:30:00-05:00", None),
    ]
    assert _monthly_mwh_from_records(recs)["mwh"] == 180.0


def test_no_records_returns_none_not_zero():
    out = _monthly_mwh_from_records([])
    assert out["mwh"] is None and out["n_used"] == 0


def test_all_null_records_returns_none():
    recs = [_rec("2026-06-01T06:00:00-05:00", None)]
    assert _monthly_mwh_from_records(recs)["mwh"] is None


def test_last_dt_normalized_to_colombia_at_month_boundary():
    """Un timestamp UTC de las 04:30Z del 1-jul es 30-jun 23:30 en Colombia.

    El día debe ser 30 (Colombia), no 1 (UTC) — evita que el "último día con
    datos" ruede al mes siguiente en lecturas de fin de mes.
    """
    recs = [
        _rec("2026-06-30T10:00:00-05:00", 100_000.0),
        _rec("2026-07-01T04:30:00Z", 150_000.0),  # = 2026-06-30 23:30 Colombia
    ]
    out = _monthly_mwh_from_records(recs)
    assert out["last_dt"].day == 30
    assert out["last_dt"].month == 6


# ── _hoy_col: fecha "hoy" en hora de Colombia (UTC-5) ────────────────────────

def test_hoy_col_uses_colombia_timezone():
    from app.api.v1.generacion_solar import _hoy_col, _COL_TZ
    expected = datetime.now(_COL_TZ).date()
    assert _hoy_col() == expected
    # Y _COL_TZ es exactamente UTC-5 sin DST
    assert _COL_TZ.utcoffset(None) == timedelta(hours=-5)


def test_hoy_col_differs_from_utc_in_evening():
    """En la franja 19:00-23:59 Bogotá (00:00-04:59 UTC) el día UTC va adelantado.

    Verifica la lógica de conversión con un instante fijo conocido.
    """
    # 2026-06-09 23:30 Bogotá == 2026-06-10 04:30 UTC
    instante_utc = datetime(2026, 6, 10, 4, 30, tzinfo=timezone.utc)
    col = timezone(timedelta(hours=-5))
    assert instante_utc.astimezone(col).date() == date(2026, 6, 9)
    assert instante_utc.date() == date(2026, 6, 10)
