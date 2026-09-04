"""Tests de la lógica pura del resumen del día (sin red ni DB)."""
import pytest

from app.api.v1 import generacion_solar as gs


# ── _sum_today_inverter_kwh ──────────────────────────────────────────────────────

def test_sum_today_only_today_entries():
    m = {
        "2026-06-09 08:00": 10,
        "2026-06-09 09:00": "15.5",   # strings también suman
        "2026-06-08 09:00": 99,        # de ayer → se ignora
    }
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == pytest.approx(25.5)


def test_sum_today_ignores_bad_values():
    m = {"2026-06-09 08:00": "n/a", "2026-06-09 09:00": 5}
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == pytest.approx(5)


@pytest.mark.parametrize("m", [None, {}])
def test_sum_today_empty(m):
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == 0.0


def test_sum_today_no_match_returns_zero():
    assert gs._sum_today_inverter_kwh({"2026-06-08 09:00": 50}, "2026-06-09") == 0.0


# ── _meter_kwh_from_detail ──────────────────────────────────────────────
# Reemplaza a _meter_kwh_from_summary: SolarView no tiene el lote de summary de
# Solenium, asi que la generacion del medidor sale de /config/project-detail/.

def test_meter_kwh_lee_el_valor_del_bloque_generation():
    detalle = {"results": {"generation": {"value": 123.4, "unit": "kWh", "complete": True}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(123.4)


def test_meter_kwh_acepta_la_respuesta_ya_desenvuelta():
    assert gs._meter_kwh_from_detail({"generation": {"value": 123.4, "unit": "kWh"}}) == pytest.approx(123.4)


def test_meter_kwh_convierte_mwh_a_kwh():
    """La unidad viene DECLARADA en el bloque y puede ser kWh o MWh -- se lee,
    nunca se asume. Verificado en vivo contra SolarView el 2026-09-03."""
    detalle = {"results": {"generation": {"value": 5.9683, "unit": "MWh"}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(5968.3)


def test_meter_kwh_tolera_mayusculas_raras_en_la_unidad():
    detalle = {"results": {"generation": {"value": 1.5, "unit": "Mwh"}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(1500.0)


@pytest.mark.parametrize("d", [
    None,
    {},
    {"results": {}},
    {"results": {"generation": {}}},
    {"results": {"generation": {"value": None}}},
    {"results": {"generation": {"value": "x"}}},
])
def test_meter_kwh_sin_dato_o_ilegible_devuelve_none(d):
    assert gs._meter_kwh_from_detail(d) is None
