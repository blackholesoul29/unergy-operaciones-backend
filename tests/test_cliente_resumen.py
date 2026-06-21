"""Tests de las funciones puras del panel de resumen del cliente (KPIs).

No tocan la DB; cubren la ventana de mes anterior, la conversión kWh→MWh y el
semáforo de cumplimiento PPA (por contrato y agregado).
"""
from datetime import date

from app.api.v1.clientes import (
    _previous_complete_month,
    _kwh_to_mwh,
    _ppa_status_for_contract,
    _aggregate_ppa_status,
)


# ── _previous_complete_month ──────────────────────────────────────────────────

def test_previous_month_mid_year():
    assert _previous_complete_month(date(2026, 6, 21)) == date(2026, 5, 1)


def test_previous_month_january_rolls_to_december():
    assert _previous_complete_month(date(2026, 1, 15)) == date(2025, 12, 1)


def test_previous_month_first_day_of_month():
    # El primer día de junio sigue mirando a mayo (mes completo anterior).
    assert _previous_complete_month(date(2026, 6, 1)) == date(2026, 5, 1)


def test_previous_month_march_after_february():
    assert _previous_complete_month(date(2026, 3, 31)) == date(2026, 2, 1)


# ── _kwh_to_mwh ───────────────────────────────────────────────────────────────

def test_kwh_to_mwh_none_is_zero():
    assert _kwh_to_mwh(None) == 0.0


def test_kwh_to_mwh_zero_is_zero():
    assert _kwh_to_mwh(0) == 0.0


def test_kwh_to_mwh_converts_and_rounds():
    assert _kwh_to_mwh(1234567) == 1234.567
    assert _kwh_to_mwh(1500) == 1.5


def test_kwh_to_mwh_accepts_decimal_like():
    from decimal import Decimal
    assert _kwh_to_mwh(Decimal("2500.0")) == 2.5


# ── _ppa_status_for_contract ──────────────────────────────────────────────────

_TODAY = date(2026, 6, 21)


def test_ppa_no_signals_defaults_green():
    # Contrato sin vencimiento y sin compromiso medido → no hay riesgo conocido.
    assert _ppa_status_for_contract(
        fecha_fin=None, gen_mwh=None, compromiso_mwh=None, today=_TODAY
    ) == "Green"


def test_ppa_expiry_far_is_green():
    assert _ppa_status_for_contract(
        fecha_fin=date(2028, 1, 1), gen_mwh=None, compromiso_mwh=None, today=_TODAY
    ) == "Green"


def test_ppa_expiry_within_six_months_is_yellow():
    assert _ppa_status_for_contract(
        fecha_fin=date(2026, 9, 1), gen_mwh=None, compromiso_mwh=None, today=_TODAY
    ) == "Yellow"


def test_ppa_expiry_within_one_month_is_red():
    assert _ppa_status_for_contract(
        fecha_fin=date(2026, 7, 5), gen_mwh=None, compromiso_mwh=None, today=_TODAY
    ) == "Red"


def test_ppa_already_expired_is_red():
    assert _ppa_status_for_contract(
        fecha_fin=date(2026, 1, 1), gen_mwh=None, compromiso_mwh=None, today=_TODAY
    ) == "Red"


def test_ppa_delivery_meets_commitment_is_green():
    assert _ppa_status_for_contract(
        fecha_fin=None, gen_mwh=100.0, compromiso_mwh=90.0, today=_TODAY
    ) == "Green"


def test_ppa_delivery_slightly_under_is_yellow():
    assert _ppa_status_for_contract(
        fecha_fin=None, gen_mwh=95.0, compromiso_mwh=100.0, today=_TODAY
    ) == "Yellow"


def test_ppa_delivery_far_under_is_red():
    assert _ppa_status_for_contract(
        fecha_fin=None, gen_mwh=50.0, compromiso_mwh=100.0, today=_TODAY
    ) == "Red"


def test_ppa_zero_commitment_ignored():
    # compromiso 0 no debe romper ni penalizar (sin compromiso que incumplir).
    assert _ppa_status_for_contract(
        fecha_fin=None, gen_mwh=0.0, compromiso_mwh=0.0, today=_TODAY
    ) == "Green"


def test_ppa_worst_dimension_wins():
    # Vencimiento lejano (Green) pero entrega muy baja (Red) → Red.
    assert _ppa_status_for_contract(
        fecha_fin=date(2028, 1, 1), gen_mwh=10.0, compromiso_mwh=100.0, today=_TODAY
    ) == "Red"


# ── _aggregate_ppa_status ─────────────────────────────────────────────────────

def test_aggregate_empty_is_na():
    assert _aggregate_ppa_status([]) == "N/A"


def test_aggregate_all_green():
    assert _aggregate_ppa_status(["Green", "Green"]) == "Green"


def test_aggregate_worst_wins_red():
    assert _aggregate_ppa_status(["Green", "Yellow", "Red"]) == "Red"


def test_aggregate_worst_wins_yellow():
    assert _aggregate_ppa_status(["Green", "Yellow", "Green"]) == "Yellow"


def test_aggregate_ignores_unknown_values():
    assert _aggregate_ppa_status(["Green", "N/A"]) == "Green"
