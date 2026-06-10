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


# ── _meter_kwh_from_summary ──────────────────────────────────────────────────────

def test_meter_kwh_parses_value():
    assert gs._meter_kwh_from_summary({"frontier_generation_kwh": "123.4"}) == pytest.approx(123.4)


@pytest.mark.parametrize("s", [None, {}, {"frontier_generation_kwh": None}, {"frontier_generation_kwh": "x"}])
def test_meter_kwh_missing_or_bad_returns_none(s):
    assert gs._meter_kwh_from_summary(s) is None
