"""Motor de reglas de negocio del monitoreo de auditoría.

`AuditRuleEngine` evalúa un evento de `audit_log` (ya mapeado a un tipo de
entidad de negocio) contra tres reglas independientes:

  * `check_outside_business_hours` — el cambio ocurrió fuera del horario laboral
    colombiano (o en fin de semana).
  * `check_unauthorized_user` — el rol del usuario no está autorizado a tocar
    esa entidad sensible.
  * `check_critical_value_change` — un campo numérico cambió por encima del
    umbral (variación > X % o valor absoluto > $Y COP).

Todos los métodos son estáticos y puros (sin BD), para poder testearlos con
`datetime`/`dict` construidos a mano. `evaluate` los orquesta y devuelve la
lista de disparos con su severidad.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytz

from app.core.config import settings
from app.models.audit_alert import (
    SEVERITY_CRITICAL,
    SEVERITY_MEDIUM,
    TRIGGER_CRITICAL_VALUE,
    TRIGGER_OUTSIDE_HOURS,
    TRIGGER_UNAUTHORIZED_USER,
)

_BOGOTA = pytz.timezone("America/Bogota")

# Mapa audit_log.tabla → tipo de entidad de negocio monitoreada.
TABLE_TO_ENTITY: dict[str, str] = {
    "liquidaciones": "liquidacion",
    "ppa_contratos": "ppa",
    "generacion_diaria": "generacion",
}

# Roles autorizados a modificar cada entidad sensible. Un cambio hecho por un
# rol fuera de este conjunto dispara `unauthorized_user`.
AUTHORIZED_ROLES: dict[str, frozenset[str]] = {
    "liquidacion": frozenset({"admin", "liquidaciones", "operaciones"}),
    "ppa": frozenset({"admin", "operaciones", "liquidaciones", "cgm"}),
    "generacion": frozenset({"admin", "operaciones", "monitoreo", "coordinador", "tecnico"}),
}


class AuditRuleEngine:
    """Reglas puras de detección. Sin estado ni acceso a BD."""

    @staticmethod
    def check_outside_business_hours(
        when: datetime,
        *,
        start_hour: Optional[int] = None,
        end_hour: Optional[int] = None,
    ) -> bool:
        """True si `when` (UTC/naive o tz-aware) cae fuera del horario laboral
        colombiano o en fin de semana."""
        if when is None:
            return False
        start = settings.BUSINESS_HOURS_START if start_hour is None else start_hour
        end = settings.BUSINESS_HOURS_END if end_hour is None else end_hour

        # Naive → se asume UTC (así lo guarda Postgres con TIMESTAMPTZ NOW()).
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        local = when.astimezone(_BOGOTA)

        if local.weekday() >= 5:  # sábado(5) / domingo(6)
            return True
        return local.hour < start or local.hour >= end

    @staticmethod
    def check_unauthorized_user(rol: Optional[str], entity_type: str) -> bool:
        """True si `rol` no está autorizado a modificar `entity_type`.

        Un usuario nulo (cambio automatizado por el sistema / scheduler) NO se
        considera no autorizado: esos jobs escriben legítimamente y de otro modo
        inundarían de alertas.
        """
        if not rol:
            return False
        allowed = AUTHORIZED_ROLES.get(entity_type)
        if allowed is None:
            return False
        return rol not in allowed

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", "").strip())
            except (ValueError, AttributeError):
                return None
        return None

    @staticmethod
    def check_critical_value_change(
        cambios: Optional[dict],
        *,
        abs_threshold_cop: Optional[float] = None,
        pct_threshold: Optional[float] = None,
    ) -> Optional[dict]:
        """Revisa el diff `{campo: {"antes":.., "despues":..}}` de un UPDATE.

        Devuelve el detalle del peor campo ofensor (o None si nada supera el
        umbral): variación relativa > `pct_threshold` o valor absoluto nuevo
        > `abs_threshold_cop`.
        """
        if not cambios:
            return None
        abs_thr = settings.AUDIT_CRITICAL_VALUE_COP if abs_threshold_cop is None else abs_threshold_cop
        pct_thr = settings.AUDIT_CRITICAL_PCT_CHANGE if pct_threshold is None else pct_threshold

        worst: Optional[dict] = None
        for campo, dv in cambios.items():
            if not isinstance(dv, dict):
                continue
            antes = AuditRuleEngine._to_float(dv.get("antes"))
            despues = AuditRuleEngine._to_float(dv.get("despues"))
            if despues is None:
                continue
            delta = abs(despues - (antes or 0.0))
            pct = (delta / abs(antes)) if antes not in (None, 0.0) else None

            hit_abs = abs(despues) > abs_thr or delta > abs_thr
            hit_pct = pct is not None and pct > pct_thr
            if not (hit_abs or hit_pct):
                continue

            candidate = {
                "campo": campo,
                "antes": antes,
                "despues": despues,
                "delta": delta,
                "pct": round(pct, 4) if pct is not None else None,
            }
            # El "peor" es el de mayor delta absoluto.
            if worst is None or delta > worst["delta"]:
                worst = candidate
        return worst

    @staticmethod
    def evaluate(
        *,
        entity_type: str,
        accion: str,
        cambios: Optional[dict],
        rol: Optional[str],
        when: datetime,
        overrides: Optional[dict] = None,
    ) -> list[dict]:
        """Corre las tres reglas y devuelve los disparos.

        Cada disparo: {"reason", "severity", "detalle"(str), "meta"(dict|None)}.
        `overrides` (de AuditRule.condition_json) puede limitar las razones
        activas y ajustar umbrales.
        """
        overrides = overrides or {}
        active_reasons = overrides.get("reasons")

        def _enabled(reason: str) -> bool:
            return active_reasons is None or reason in active_reasons

        triggered: list[dict] = []

        if _enabled(TRIGGER_OUTSIDE_HOURS) and AuditRuleEngine.check_outside_business_hours(when):
            local = (
                when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when
            ).astimezone(_BOGOTA)
            triggered.append({
                "reason": TRIGGER_OUTSIDE_HOURS,
                "severity": SEVERITY_MEDIUM,
                "detalle": f"Cambio fuera de horario laboral ({local:%Y-%m-%d %H:%M} hora Colombia).",
                "meta": {"hora_local": local.isoformat()},
            })

        if _enabled(TRIGGER_UNAUTHORIZED_USER) and AuditRuleEngine.check_unauthorized_user(rol, entity_type):
            triggered.append({
                "reason": TRIGGER_UNAUTHORIZED_USER,
                "severity": SEVERITY_CRITICAL,
                "detalle": f"Usuario con rol '{rol}' no autorizado para modificar {entity_type}.",
                "meta": {"rol": rol},
            })

        if _enabled(TRIGGER_CRITICAL_VALUE) and accion == "UPDATE":
            worst = AuditRuleEngine.check_critical_value_change(
                cambios,
                abs_threshold_cop=overrides.get("critical_value_cop"),
                pct_threshold=overrides.get("critical_pct"),
            )
            if worst:
                pct_txt = f"{worst['pct'] * 100:.1f}%" if worst["pct"] is not None else "n/d"
                triggered.append({
                    "reason": TRIGGER_CRITICAL_VALUE,
                    "severity": SEVERITY_CRITICAL,
                    "detalle": (
                        f"Cambio crítico en '{worst['campo']}': "
                        f"{worst['antes']} → {worst['despues']} (Δ {worst['delta']:.0f}, {pct_txt})."
                    ),
                    "meta": worst,
                })

        return triggered
