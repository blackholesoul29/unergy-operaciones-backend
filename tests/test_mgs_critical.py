"""Tests del detector de eventos críticos MGS (lógica pura, sin DB).

Cubre clasificación caída de producción / desconexión total, la ventana de
duración sostenida para desconexión y el debounce anti-duplicados.
"""
from datetime import datetime, timedelta

from app.api.v1.mgs import (
    MGSCriticalDetector,
    _solar_fraction_elapsed,
    _expected_so_far_kwh,
)
from app.schemas.fallas import TipoAlertaMGS

T0 = datetime(2026, 6, 25, 10, 0, 0)


def _det():
    return MGSCriticalDetector(drop_threshold=0.20, disconnection_minutes=15)


# ── Caída de producción ───────────────────────────────────────────────────────
def test_normal_generation_no_alert():
    d = _det()
    assert d.evaluate(1, current_gen=100.0, expected_gen=100.0, now=T0) is None


def test_slight_drop_below_threshold_no_alert():
    # 10% por debajo de lo esperado, umbral 20% → no alerta
    d = _det()
    assert d.evaluate(1, current_gen=90.0, expected_gen=100.0, now=T0) is None


def test_critical_drop_triggers_caida_produccion():
    # 50% por debajo de lo esperado → caída crítica
    d = _det()
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0) == TipoAlertaMGS.CAIDA_PRODUCCION


def test_drop_exactly_at_threshold_no_alert():
    # current == expected*(1-0.20) = 80 → no es estrictamente menor → sin alerta
    d = _det()
    assert d.evaluate(1, current_gen=80.0, expected_gen=100.0, now=T0) is None


def test_no_expected_baseline_no_alert():
    d = _det()
    assert d.evaluate(1, current_gen=0.0, expected_gen=None, now=T0) is None
    assert d.evaluate(1, current_gen=0.0, expected_gen=0.0, now=T0) is None


# ── Desconexión total (requiere duración sostenida) ───────────────────────────
def test_zero_generation_not_immediately_disconnection():
    # Primer poll en cero: aún no se declara desconexión (espera duración)
    d = _det()
    assert d.evaluate(1, current_gen=0.0, expected_gen=100.0, now=T0) is None


def test_sustained_zero_triggers_desconexion_total():
    d = _det()
    assert d.evaluate(1, current_gen=0.0, expected_gen=100.0, now=T0) is None
    # 16 min después, sigue en cero → desconexión total
    later = T0 + timedelta(minutes=16)
    assert d.evaluate(1, current_gen=0.0, expected_gen=100.0, now=later) == TipoAlertaMGS.DESCONEXION_TOTAL


def test_zero_then_recovery_before_duration_no_alert():
    d = _det()
    assert d.evaluate(1, current_gen=0.0, expected_gen=100.0, now=T0) is None
    # vuelve a generar antes de cumplir la duración → sin alerta y se resetea
    back = T0 + timedelta(minutes=5)
    assert d.evaluate(1, current_gen=100.0, expected_gen=100.0, now=back) is None
    # nuevo cero arranca de cero la ventana
    again = back + timedelta(minutes=1)
    assert d.evaluate(1, current_gen=0.0, expected_gen=100.0, now=again) is None


# ── Debounce ──────────────────────────────────────────────────────────────────
def test_ongoing_drop_alerts_only_once():
    d = _det()
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0) == TipoAlertaMGS.CAIDA_PRODUCCION
    # mismo evento en curso → no re-alerta
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0 + timedelta(minutes=10)) is None
    assert d.evaluate(1, current_gen=55.0, expected_gen=100.0, now=T0 + timedelta(minutes=20)) is None


def test_recovery_then_new_drop_realerts():
    d = _det()
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0) == TipoAlertaMGS.CAIDA_PRODUCCION
    # recuperación
    assert d.evaluate(1, current_gen=100.0, expected_gen=100.0, now=T0 + timedelta(minutes=10)) is None
    # nueva caída → vuelve a alertar
    assert d.evaluate(1, current_gen=40.0, expected_gen=100.0, now=T0 + timedelta(minutes=20)) == TipoAlertaMGS.CAIDA_PRODUCCION


# ── Rollback del debounce cuando NO se pudo notificar ──────────────────────────
def test_rollback_reopens_debounce_for_retry():
    # Una transición que se marcó activa pero cuya falla/notificación falló debe
    # poder reintentarse en el siguiente ciclo (no perder una alerta crítica).
    d = _det()
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0) == TipoAlertaMGS.CAIDA_PRODUCCION
    # mismo evento en curso → debounce normal
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0 + timedelta(minutes=1)) is None
    # se revierte (no se pudo notificar) → la próxima evaluación vuelve a emitir
    d.rollback(1)
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0 + timedelta(minutes=2)) == TipoAlertaMGS.CAIDA_PRODUCCION


def test_rollback_unknown_project_is_noop():
    d = _det()
    d.rollback(999)  # no debe lanzar aunque el proyecto no tenga incidencia activa
    assert d.evaluate(1, current_gen=100.0, expected_gen=100.0, now=T0) is None


def test_independent_projects_tracked_separately():
    d = _det()
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0) == TipoAlertaMGS.CAIDA_PRODUCCION
    # otro proyecto sano → sin alerta; no afecta al primero
    assert d.evaluate(2, current_gen=100.0, expected_gen=100.0, now=T0) is None
    assert d.evaluate(1, current_gen=50.0, expected_gen=100.0, now=T0 + timedelta(minutes=1)) is None


# ── Baseline esperado ─────────────────────────────────────────────────────────
def test_solar_fraction_outside_daylight_is_zero():
    assert _solar_fraction_elapsed(datetime(2026, 6, 25, 5, 0)) == 0.0   # antes del amanecer
    assert _solar_fraction_elapsed(datetime(2026, 6, 25, 19, 0)) == 0.0  # después del atardecer


def test_solar_fraction_midday_is_half():
    # 12:00 está a mitad de la ventana 06:00–18:00
    assert _solar_fraction_elapsed(datetime(2026, 6, 25, 12, 0)) == 0.5


def test_expected_so_far_prorates_p50_by_fraction():
    # Junio (mes 6) = 30 días, P50 mensual 300 kWh → 10 kWh/día; a mitad del día → 5
    p50 = [0] * 12
    p50[5] = 300.0
    out = _expected_so_far_kwh(p50, datetime(2026, 6, 25, 12, 0), 0.5)
    assert out == 5.0


def test_expected_so_far_none_when_no_baseline():
    assert _expected_so_far_kwh(None, datetime(2026, 6, 25, 12, 0), 0.5) is None
    assert _expected_so_far_kwh([0] * 12, datetime(2026, 6, 25, 12, 0), 0.5) is None
    # fracción 0 (de noche) → sin expectativa
    assert _expected_so_far_kwh([300] * 12, datetime(2026, 6, 25, 2, 0), 0.0) is None


# ── check_mgs_critical_events: no perder la alerta si falla la creación ─────────
# Estas pruebas inyectan ``readings``/``now`` y monkeypatchean los helpers de BD,
# así ejercitan el flujo del scheduler sin tocar Postgres.
_READING = {"proyecto_id": 1, "nombre": "P1", "current_gen": 50.0, "expected_gen": 100.0}


class _StubDB:
    """Sesión mínima: solo necesita ``rollback`` para el manejo de errores."""
    def rollback(self):
        pass


def _fresh_detector(monkeypatch):
    from app.api.v1 import mgs as mgs_mod
    monkeypatch.setattr(
        mgs_mod, "_detector",
        MGSCriticalDetector(drop_threshold=0.20, disconnection_minutes=15),
    )
    monkeypatch.setattr(mgs_mod, "_has_open_mgs_falla", lambda db, pid, tipo: False)
    monkeypatch.setattr(mgs_mod, "_notify_ops_users", lambda *a, **k: 0)
    return mgs_mod


def test_check_retries_when_falla_creation_returns_none(monkeypatch):
    # Catálogos/usuario ausentes → _create_falla_for_event devuelve None. La
    # alerta NO debe quedar silenciada para siempre: el próximo ciclo reintenta.
    mgs_mod = _fresh_detector(monkeypatch)
    calls = {"n": 0}

    def _fail_create(db, reading, tipo, now):
        calls["n"] += 1
        return None

    monkeypatch.setattr(mgs_mod, "_create_falla_for_event", _fail_create)

    assert mgs_mod.check_mgs_critical_events(db=_StubDB(), readings=[_READING], now=T0) == []
    assert mgs_mod.check_mgs_critical_events(
        db=_StubDB(), readings=[_READING], now=T0 + timedelta(minutes=1)) == []
    # Sin el rollback del debounce el 2º ciclo quedaría silenciado (calls == 1).
    assert calls["n"] == 2


def test_check_retries_when_creation_raises(monkeypatch):
    # Error transitorio de BD durante la creación → debe reintentarse, no perderse.
    mgs_mod = _fresh_detector(monkeypatch)
    calls = {"n": 0}

    def _raise(db, reading, tipo, now):
        calls["n"] += 1
        raise RuntimeError("blip de BD")

    monkeypatch.setattr(mgs_mod, "_create_falla_for_event", _raise)

    assert mgs_mod.check_mgs_critical_events(db=_StubDB(), readings=[_READING], now=T0) == []
    assert mgs_mod.check_mgs_critical_events(
        db=_StubDB(), readings=[_READING], now=T0 + timedelta(minutes=1)) == []
    assert calls["n"] == 2


def test_check_does_not_rerun_after_success(monkeypatch):
    # Tras una creación exitosa el debounce SÍ se mantiene (no spamear fallas).
    mgs_mod = _fresh_detector(monkeypatch)
    calls = {"n": 0}

    class _Falla:
        id = 42
        codigo_interno = "MGS-0001"

    def _ok_create(db, reading, tipo, now):
        calls["n"] += 1
        return _Falla()

    monkeypatch.setattr(mgs_mod, "_create_falla_for_event", _ok_create)

    assert mgs_mod.check_mgs_critical_events(db=_StubDB(), readings=[_READING], now=T0) == [42]
    assert mgs_mod.check_mgs_critical_events(
        db=_StubDB(), readings=[_READING], now=T0 + timedelta(minutes=1)) == []
    assert calls["n"] == 1  # no reintenta una incidencia ya notificada
