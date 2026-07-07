"""Tests del motor de reglas de auditoría (funciones puras, sin BD).

Cubren las tres reglas de `AuditRuleEngine` (horario laboral colombiano, usuario
no autorizado, cambio de valor crítico) y la orquestación de `evaluate`.
"""
import pytz

from app.services.audit_rules import AuditRuleEngine
from app.models.audit_alert import (
    TRIGGER_CRITICAL_VALUE,
    TRIGGER_OUTSIDE_HOURS,
    TRIGGER_UNAUTHORIZED_USER,
)

_BOGOTA = pytz.timezone("America/Bogota")


def _bogota(y, m, d, hh, mm=0):
    return _BOGOTA.localize(__import__("datetime").datetime(y, m, d, hh, mm))


# ── horario laboral ──────────────────────────────────────────────────────────
def test_cambio_a_las_3am_es_fuera_de_horario():
    # 2026-07-07 es martes → solo la hora lo hace "fuera de horario"
    assert AuditRuleEngine.check_outside_business_hours(_bogota(2026, 7, 7, 3)) is True


def test_cambio_a_las_2pm_dia_habil_esta_dentro_de_horario():
    assert AuditRuleEngine.check_outside_business_hours(_bogota(2026, 7, 7, 14)) is False


def test_fin_de_semana_siempre_fuera_de_horario():
    # 2026-07-11 es sábado
    assert AuditRuleEngine.check_outside_business_hours(_bogota(2026, 7, 11, 14)) is True


# ── usuario no autorizado ────────────────────────────────────────────────────
def test_rol_monitoreo_no_autorizado_para_liquidacion():
    assert AuditRuleEngine.check_unauthorized_user("monitoreo", "liquidacion") is True


def test_rol_liquidaciones_autorizado_para_liquidacion():
    assert AuditRuleEngine.check_unauthorized_user("liquidaciones", "liquidacion") is False


def test_usuario_sistema_sin_rol_no_es_no_autorizado():
    # Cambios automatizados (sin usuario) no deben inundar de alertas.
    assert AuditRuleEngine.check_unauthorized_user(None, "generacion") is False


# ── cambio de valor crítico ──────────────────────────────────────────────────
def test_valor_absoluto_supera_umbral():
    cambios = {"valor_neto_cop": {"antes": 1_000_000, "despues": 60_000_000}}
    worst = AuditRuleEngine.check_critical_value_change(cambios)
    assert worst is not None
    assert worst["campo"] == "valor_neto_cop"


def test_variacion_porcentual_supera_umbral():
    cambios = {"tarifa": {"antes": 1000, "despues": 1200}}  # +20% > 10%
    worst = AuditRuleEngine.check_critical_value_change(cambios)
    assert worst is not None
    assert worst["pct"] == 0.2


def test_cambio_pequeno_no_es_critico():
    cambios = {"tarifa": {"antes": 1000, "despues": 1050}}  # +5%, valor bajo
    assert AuditRuleEngine.check_critical_value_change(cambios) is None


def test_sin_cambios_no_es_critico():
    assert AuditRuleEngine.check_critical_value_change(None) is None
    assert AuditRuleEngine.check_critical_value_change({}) is None


# ── evaluate (orquestación) ──────────────────────────────────────────────────
def test_evaluate_dispara_multiples_razones():
    triggered = AuditRuleEngine.evaluate(
        entity_type="liquidacion",
        accion="UPDATE",
        cambios={"valor_neto_cop": {"antes": 1_000_000, "despues": 90_000_000}},
        rol="monitoreo",
        when=_bogota(2026, 7, 11, 3),  # sábado 3am → fuera de horario también
    )
    reasons = {t["reason"] for t in triggered}
    assert TRIGGER_OUTSIDE_HOURS in reasons
    assert TRIGGER_UNAUTHORIZED_USER in reasons
    assert TRIGGER_CRITICAL_VALUE in reasons


def test_evaluate_insert_no_dispara_critical_value():
    triggered = AuditRuleEngine.evaluate(
        entity_type="liquidacion",
        accion="INSERT",
        cambios=None,
        rol="liquidaciones",
        when=_bogota(2026, 7, 7, 14),  # dentro de horario, rol autorizado
    )
    assert triggered == []


def test_evaluate_respeta_reasons_del_override():
    triggered = AuditRuleEngine.evaluate(
        entity_type="liquidacion",
        accion="UPDATE",
        cambios={"valor_neto_cop": {"antes": 1_000_000, "despues": 90_000_000}},
        rol="monitoreo",
        when=_bogota(2026, 7, 11, 3),
        overrides={"reasons": [TRIGGER_CRITICAL_VALUE]},
    )
    reasons = {t["reason"] for t in triggered}
    assert reasons == {TRIGGER_CRITICAL_VALUE}
