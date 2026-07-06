"""Servicio de cálculo de impacto de mantenimiento.

Estima la energía perdida y su impacto económico de un evento de mantenimiento
en una ventana [start, end] para una planta:

  1. Energía esperada (teórica) — perfil histórico de la planta en la ventana
     (columna ``kwh_p90`` de ``generacion_diaria``); si no hay perfil, se acepta
     el valor esperado provisto explícitamente por quien registra el evento.
  2. Energía real — ``kwh_real`` de ``generacion_diaria`` en la ventana; si el
     mantenimiento fue downtime total y no hay dato, se asume 0.
  3. Energía perdida = max(0, esperada − real).
  4. Impacto económico = energía perdida × precio (tarifa PPA vigente del
     proyecto o, en su defecto, un precio de energía de referencia).
  5. Bandera de riesgo de penalización PPA si la energía perdida supera un umbral.

El núcleo de cálculo (`compute_metrics`) es una función pura y testeable; la
resolución de datos desde la BD vive en `calculate_impact`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.generacion import GeneracionDiaria
from app.models.proyectos import Proyecto

# Precio de energía de referencia (COP/kWh) — mismo valor que usa el estimador
# de impacto de fallas (app/api/v1/fallas.py) para mantener coherencia.
PRECIO_ENERGIA_COP_KWH = 800.0

# Umbral de energía perdida (kWh) por encima del cual se marca riesgo de
# penalización PPA. Cualquier pérdida > 0 se considera relevante para el flag.
PPA_PENALTY_THRESHOLD_KWH = 0.0

_COL_TZ = timezone(timedelta(hours=-5))  # Colombia (UTC-5)


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def compute_metrics(
    expected_kwh: Optional[float],
    actual_kwh: Optional[float],
    precio_cop_kwh: float = PRECIO_ENERGIA_COP_KWH,
    penalty_threshold_kwh: float = PPA_PENALTY_THRESHOLD_KWH,
) -> dict:
    """Calcula energía perdida, impacto económico y bandera de penalización.

    Función pura. `expected`/`actual` pueden ser None (sin dato). La energía
    perdida solo se calcula cuando se conoce la esperada; la real ausente se
    trata como 0 (downtime total).
    """
    if expected_kwh is None:
        lost = None
    else:
        actual = actual_kwh if actual_kwh is not None else 0.0
        lost = round(max(0.0, expected_kwh - actual), 2)

    financial = round(lost * precio_cop_kwh, 2) if lost is not None else None
    penalty = bool(lost is not None and lost > penalty_threshold_kwh)

    return {
        "expected_generation_kwh": round(expected_kwh, 2) if expected_kwh is not None else None,
        "actual_generation_kwh": round(actual_kwh, 2) if actual_kwh is not None else None,
        "lost_energy_kwh": lost,
        "financial_impact_cop": financial,
        "ppa_penalty_risk_flag": penalty,
        "precio_cop_kwh": precio_cop_kwh,
    }


class ImpactCalculator:
    """Calcula el impacto de un evento de mantenimiento sobre una planta."""

    def __init__(self, db: Session):
        self.db = db

    def _precio_cop_kwh(self, proyecto: Optional[Proyecto], ref: date) -> float:
        """Precio COP/kWh: tarifa PPA vigente del proyecto en el período de `ref`;
        si no hay contrato/tarifa, cae al precio de energía de referencia."""
        if proyecto is None:
            return PRECIO_ENERGIA_COP_KWH
        try:
            contratos = list(proyecto.ppa_contratos or [])
        except Exception:
            contratos = []
        for contrato in contratos:
            for tarifa in (getattr(contrato, "tarifas", None) or []):
                if tarifa.año == ref.year and tarifa.mes == ref.month and tarifa.tarifa is not None:
                    # Tarifas PPA se guardan en COP/kWh en la plataforma.
                    return float(tarifa.tarifa)
        return PRECIO_ENERGIA_COP_KWH

    def _generacion_ventana(self, proyecto_id: int, start: date, end: date) -> tuple[Optional[float], Optional[float]]:
        """(esperada, real) en kWh sumando generacion_diaria entre `start` y `end`
        (ambos inclusive). Devuelve None en cada componente si no hay ningún dato."""
        row = (
            self.db.query(
                func.sum(GeneracionDiaria.kwh_p90).label("esperada"),
                func.sum(GeneracionDiaria.kwh_real).label("real"),
            )
            .filter(
                GeneracionDiaria.proyecto_id == proyecto_id,
                GeneracionDiaria.fecha >= start,
                GeneracionDiaria.fecha <= end,
            )
            .first()
        )
        if row is None:
            return None, None
        return _to_float(row.esperada), _to_float(row.real)

    def calculate_impact(
        self,
        proyecto_id: int,
        start: datetime,
        end: datetime,
        expected_generation_kwh: Optional[float] = None,
        actual_generation_kwh: Optional[float] = None,
    ) -> dict:
        """Devuelve el diccionario de métricas del evento de mantenimiento.

        Si `expected/actual` se pasan explícitamente, se respetan (entrada manual);
        de lo contrario se derivan del perfil histórico de `generacion_diaria` en
        la ventana [start, end].
        """
        proyecto = self.db.get(Proyecto, proyecto_id)

        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        gen_esperada, gen_real = None, None
        if expected_generation_kwh is None or actual_generation_kwh is None:
            gen_esperada, gen_real = self._generacion_ventana(proyecto_id, start_date, end_date)

        expected = expected_generation_kwh if expected_generation_kwh is not None else gen_esperada
        actual = actual_generation_kwh if actual_generation_kwh is not None else gen_real

        precio = self._precio_cop_kwh(proyecto, start_date)
        return compute_metrics(expected, actual, precio_cop_kwh=precio)
