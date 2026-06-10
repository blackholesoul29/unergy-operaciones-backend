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


# ── O&M (financiero): red de seguridad sobre cálculos puros existentes ───────
# Estos tests NO cambian la lógica; fijan el comportamiento actual para que
# cualquier edición futura (humana o de Samantha) que altere un número de dinero
# falle de inmediato. Acordar cambios reales con Finanzas antes de modificarlos.

from app.services.om_calculator import (
    factor_acumulado,
    calcular_prorrateo,
    calcular_proyecto,
    _redondear,
)

IPC = {2024: 0.0928, 2025: 0.052, 2026: 0.051}


def test_factor_acumulado_ejemplo_documentado():
    # inicio 2023, periodo 2026 → (1.0928)(1.052)(1.051)
    assert round(factor_acumulado(2023, 2026, IPC), 6) == 1.208257


def test_factor_acumulado_anio_base_sin_indexacion():
    assert factor_acumulado(2026, 2026, IPC) == 1.0
    assert factor_acumulado(2027, 2026, IPC) == 1.0  # inicio > periodo


def test_redondear_half_up_y_cop_entero():
    assert _redondear(100.5) == 101
    assert _redondear(100.49) == 100
    assert _redondear(2.5) == 3
    assert isinstance(_redondear(1_000_000.0), int)


def test_prorrateo_menos_de_15_dias_no_factura():
    # inicio 20-jun: 30-20+1 = 11 días ≤ 15
    assert calcular_prorrateo(date(2026, 6, 20), "2026-06") == ("No se factura", 0.0)


def test_prorrateo_mas_de_15_dias_parcial():
    # inicio 10-jun: 30-10+1 = 21 días > 15 → 21/30 = 0.7
    label, factor = calcular_prorrateo(date(2026, 6, 10), "2026-06")
    assert label == "21/30 días" and factor == 0.7


def test_prorrateo_periodo_posterior_es_completo():
    assert calcular_prorrateo(date(2026, 5, 1), "2026-06") == ("Completo", 1.0)


def test_prorrateo_periodo_anterior_al_inicio_no_factura():
    assert calcular_prorrateo(date(2026, 6, 1), "2026-05") == ("No se factura", 0.0)


def test_calcular_proyecto_sin_valor_base_queda_deshabilitado():
    out = calcular_proyecto(
        contrato_id=1, nombre_proyecto="X", fecha_inicio=date(2025, 1, 1),
        valor_base_anual=None, periodo="2026-06", ipc_tasas=IPC,
    )
    assert out["habilitado"] is False
    assert out["valor_a_facturar"] is None


def test_calcular_proyecto_mes_completo_oracle_entero():
    # IPC 0 ⇒ factor 1.0; base 12.000.000 / 12 = 1.000.000 exacto, mes completo
    out = calcular_proyecto(
        contrato_id=1, nombre_proyecto="X", fecha_inicio=date(2024, 1, 1),
        valor_base_anual=12_000_000, periodo="2026-06", ipc_tasas={},
    )
    assert out["habilitado"] is True
    assert out["factor_acumulado"] == 1.0
    assert out["prorrateo_label"] == "Completo"
    assert out["valor_mes_completo"] == 1_000_000
    assert out["valor_a_facturar"] == 1_000_000


def test_calcular_proyecto_prorrateo_aplica_al_valor():
    # mes de inicio, 21/30 días ⇒ 1.000.000 * 0.7 = 700.000
    out = calcular_proyecto(
        contrato_id=1, nombre_proyecto="X", fecha_inicio=date(2026, 6, 10),
        valor_base_anual=12_000_000, periodo="2026-06", ipc_tasas={},
    )
    assert out["prorrateo_factor"] == 0.7
    assert out["valor_a_facturar"] == 700_000
