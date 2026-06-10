"""Tests de la lógica pura de proximos_energizar (sin red ni DB)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.api.v1 import proximos_energizar as pe


# ── _parse_iso_date ─────────────────────────────────────────────────────────────

def test_parse_iso_date_with_z():
    assert pe._parse_iso_date("2026-05-25T17:00:00Z") == date(2026, 5, 25)


def test_parse_iso_date_date_only():
    assert pe._parse_iso_date("2026-01-14") == date(2026, 1, 14)


@pytest.mark.parametrize("bad", [None, "", "no-es-fecha", "2026-13-99"])
def test_parse_iso_date_invalid_returns_none(bad):
    assert pe._parse_iso_date(bad) is None


# ── _project_monthly_mwh ────────────────────────────────────────────────────────

def test_monthly_mwh_typical_990kwp():
    # 990 kWp * 4.3 kWh/kWp/día * 30 / 1000 = 127.71 MWh
    assert pe._project_monthly_mwh(990, 4.3) == pytest.approx(127.71, abs=0.01)


@pytest.mark.parametrize("bad", [None, 0, -5])
def test_monthly_mwh_no_power_returns_none(bad):
    assert pe._project_monthly_mwh(bad, 4.3) is None


# ── _estimate_energization ──────────────────────────────────────────────────────

def test_estimate_uses_stage_offset_from_last_change():
    last = datetime(2026, 1, 1, tzinfo=timezone.utc)
    got = pe._estimate_energization("construction", last)
    assert got == date(2026, 1, 1) + timedelta(days=pe._STAGE_OFFSET_DAYS["construction"])


def test_estimate_accepts_plain_date():
    last = date(2026, 1, 1)
    got = pe._estimate_energization("deploy", last)
    assert got == date(2026, 1, 1) + timedelta(days=pe._STAGE_OFFSET_DAYS["deploy"])


def test_estimate_none_when_no_date():
    assert pe._estimate_energization("construction", None) is None


# ── _ENERG_MILESTONE_RE ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Hito 5 - RETIE y legalización",
    "HITO 4. RETIE Y LEGALIZACIÓN",
    "Energización del proyecto",
    "Puesta en marcha",
])
def test_energ_regex_matches(name):
    assert pe._ENERG_MILESTONE_RE.search(name)


@pytest.mark.parametrize("name", [
    "Hito 1. Ingeniería de detalle",
    "Equipos principales en puerto",
    "Beneficios tributarios",
])
def test_energ_regex_no_match(name):
    assert not pe._ENERG_MILESTONE_RE.search(name)


# ── _pick_energization_milestone (núcleo) ───────────────────────────────────────

def _ms(name, planned, dt, pct=None):
    return {"name": name, "planned_date": planned, "date": dt,
            "progress": {"calculated_percentage": pct} if pct is not None else {}}


def test_pick_prefers_retie_by_name_even_if_not_last():
    milestones = [
        _ms("Hito 5 - RETIE y legalización", "2025-12-30T17:00:00Z", "2026-02-16T17:00:00Z", 37.04),
        _ms("Hito 6 - Cierre administrativo", "2026-03-30T17:00:00Z", "2026-04-01T17:00:00Z", 0.0),
    ]
    got = pe._pick_energization_milestone(milestones)
    assert got["energization_date"] == date(2026, 2, 16)
    assert got["avance_pct"] == 37.04
    assert "RETIE" in got["milestone"]


def test_pick_falls_back_to_final_milestone_when_no_name_match():
    milestones = [
        _ms("Hito 1. Ingeniería", "2025-08-05T17:00:00Z", "2025-09-01T17:00:00Z", 100),
        _ms("Hito 3. Equipos", "2025-09-26T17:00:00Z", "2025-12-10T17:00:00Z", 50),
    ]
    got = pe._pick_energization_milestone(milestones)
    # el de mayor planned_date
    assert got["energization_date"] == date(2025, 12, 10)


def test_pick_uses_planned_date_when_no_projected_date():
    milestones = [_ms("RETIE", "2026-07-01T17:00:00Z", None, 10)]
    got = pe._pick_energization_milestone(milestones)
    assert got["energization_date"] == date(2026, 7, 1)


def test_pick_avance_falls_back_to_activity_percentage():
    m = {"name": "RETIE", "planned_date": "2026-07-01T00:00:00Z", "date": None,
         "progress": {"activity_percentage": 22.5}}
    assert pe._pick_energization_milestone([m])["avance_pct"] == 22.5


def test_pick_none_when_empty():
    assert pe._pick_energization_milestone([]) is None


def test_pick_none_when_no_dated_milestones():
    assert pe._pick_energization_milestone([{"name": "RETIE", "progress": {}}]) is None


def test_pick_real_project_103_shape():
    """Réplica de los 7 hitos reales del proyecto 103 (COLCEST55P2)."""
    milestones = [
        _ms("Hito 1. Ingeniería de detalle", "2025-08-05T17:00:00Z", "2025-11-11T17:00:00Z", 100),
        _ms("Hito 2. Equipos en puerto", "2025-08-29T17:00:00Z", "2025-08-29T17:00:00Z", 100),
        _ms("Hito 3. Equipos en el proyecto", "2025-09-26T17:00:00Z", "2025-12-10T17:00:00Z", 80),
        _ms("Hito 4 - Instalación del proyecto", "2025-11-10T17:00:00Z", "2026-05-27T17:00:00Z", 40),
        _ms("Hito 5 - RETIE y legalización", "2025-12-30T17:00:00Z", "2026-02-16T17:00:00Z", 37.04),
    ]
    got = pe._pick_energization_milestone(milestones)
    assert got["milestone"] == "Hito 5 - RETIE y legalización"
    assert got["energization_date"] == date(2026, 2, 16)
    assert got["avance_pct"] == 37.04


# ── _STAGE_TO_STATUS ────────────────────────────────────────────────────────────

def test_stage_status_mapping():
    assert pe._STAGE_TO_STATUS["deploy"] == "Próximo a energizar"
    assert pe._STAGE_TO_STATUS["construction"] == "En construcción"
    assert pe._STAGE_TO_STATUS["operation"] == "Energizado"


def test_pipeline_stages_ordered_closest_first():
    # deploy (PEM/pruebas, última etapa antes de operation) es la más cercana a
    # energizar → va primero para el ORDER BY array_position.
    assert pe._PIPELINE_STAGES[0] == "deploy"
    assert "operation" not in pe._PIPELINE_STAGES  # ya energizado, no es "próximo"


# Etapas reales de minifarm_project (originabotdb). Fuente: docs/UNERGY_DATABASE_ATLAS.md
# y docs/unergy-data-graph.md. Guarda contra etapas inventadas (p.ej. el viejo "uci").
_CANONICAL_STAGES = {
    "prospect", "due_diligence", "viability", "negociation", "signed",
    "bt_and_contract", "construction", "deploy", "operation",
    "portfolio", "reevaluation", "paused", "dead",
}


def test_pipeline_and_status_stages_are_canonical():
    assert set(pe._PIPELINE_STAGES) <= _CANONICAL_STAGES
    assert set(pe._STAGE_TO_STATUS) <= _CANONICAL_STAGES
    assert set(pe._STAGE_OFFSET_DAYS) <= _CANONICAL_STAGES


def test_status_labels_match_frontend_options():
    # Deben pertenecer a STATUS_OPTIONS de ProyectosProximosEnergizar.vue.
    frontend_options = {"En construcción", "Pruebas", "Próximo a energizar", "Energizado"}
    assert set(pe._STAGE_TO_STATUS.values()) <= frontend_options


# ── _derive_commercial_name ─────────────────────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    ("COLSUCT3P1_MORROA_SUR", "Morroa Sur"),      # prefijo de código con dígitos → se descarta
    ("COLBOLT2P3_LA_UNION", "La Union"),
    ("COLSUCT3P1_MORROA_SUR_2", "Morroa Sur 2"),  # el sitio puede tener sufijo numérico
    ("MORROSQUILLO_2", "Morrosquillo 2"),         # 1er token sin pinta de código → se conserva
    ("SINGLEWORD", "Singleword"),                  # sin separador
])
def test_derive_commercial_name(code, expected):
    assert pe._derive_commercial_name(code) == expected


@pytest.mark.parametrize("bad", [None, ""])
def test_derive_commercial_name_empty(bad):
    assert pe._derive_commercial_name(bad) == ""


# ── _sunfactory_token: reúso de credenciales Solenium ───────────────────────────

class _FakeResp:
    def raise_for_status(self): pass
    def json(self): return {"access": "tok-123"}


class _FakeClient:
    last_json = None
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def post(self, url, json=None):
        _FakeClient.last_json = json
        return _FakeResp()


def _set(monkeypatch, **vals):
    for k, v in vals.items():
        monkeypatch.setattr(pe.settings, k, v, raising=False)


def test_sunfactory_token_falls_back_to_solenium_creds(monkeypatch):
    # Sin credenciales SUNFACTORY_* dedicadas → debe reusar SOLENIUM_USER/PASS.
    _set(monkeypatch, SUNFACTORY_USERNAME="", SUNFACTORY_PASSWORD="",
         SUNFACTORY_AUTH_URL="https://auth.solenium.co/api/token/",
         SOLENIUM_USER="sol-user", SOLENIUM_PASS="sol-pass")
    monkeypatch.setattr(pe.httpx, "Client", _FakeClient)
    assert pe._sunfactory_token() == "tok-123"
    assert _FakeClient.last_json == {"username": "sol-user", "password": "sol-pass"}


def test_sunfactory_token_prefers_dedicated_creds(monkeypatch):
    # Si SUNFACTORY_* están seteadas, ganan sobre las de Solenium.
    _set(monkeypatch, SUNFACTORY_USERNAME="sf-user", SUNFACTORY_PASSWORD="sf-pass",
         SUNFACTORY_AUTH_URL="https://auth.solenium.co/api/token/",
         SOLENIUM_USER="sol-user", SOLENIUM_PASS="sol-pass")
    monkeypatch.setattr(pe.httpx, "Client", _FakeClient)
    assert pe._sunfactory_token() == "tok-123"
    assert _FakeClient.last_json["username"] == "sf-user"


def test_sunfactory_token_none_without_any_creds(monkeypatch):
    _set(monkeypatch, SUNFACTORY_USERNAME="", SUNFACTORY_PASSWORD="",
         SOLENIUM_USER="", SOLENIUM_PASS="")
    assert pe._sunfactory_token() is None
