"""Impacto de un evento de mantenimiento sobre una planta.

Energía perdida, impacto económico y bandera de riesgo de penalización PPA.
**Estos tres campos no se editan a mano**: se recalculan en cada creación y
edición, para que siempre reflejen la ventana de tiempo y la generación del
evento.
"""

from datetime import date, datetime

from django.db.models import Sum

from apps.ppa import models as ppa_models
from apps.proyectos import models as py_models

# Precio de referencia, el mismo que usa el estimador de impacto de fallas para
# que las dos cifras sean comparables.
PRECIO_ENERGIA_COP_KWH = 800.0

# Cualquier pérdida por encima de cero se considera relevante para la bandera.
UMBRAL_PENALIZACION_KWH = 0.0


def _float(valor):
    return None if valor is None else float(valor)


def metricas(
    esperada: float | None, real: float | None,
    precio_cop_kwh: float = PRECIO_ENERGIA_COP_KWH,
    umbral_kwh: float = UMBRAL_PENALIZACION_KWH,
) -> dict:
    """Función PURA. `esperada` y `real` pueden ser `None` (sin dato).

    La energía perdida solo se calcula si se conoce la ESPERADA. La real
    ausente se trata como cero, que es lo que significa un apagón total; la
    esperada ausente, en cambio, no permite decir cuánto se perdió.
    """
    if esperada is None:
        perdida = None
    else:
        perdida = round(max(0.0, esperada - (real if real is not None else 0.0)), 2)

    return {
        "expected_generation_kwh": (
            round(esperada, 2) if esperada is not None else None
        ),
        "actual_generation_kwh": round(real, 2) if real is not None else None,
        "lost_energy_kwh": perdida,
        "financial_impact_cop": (
            round(perdida * precio_cop_kwh, 2) if perdida is not None else None
        ),
        "ppa_penalty_risk_flag": bool(
            perdida is not None and perdida > umbral_kwh
        ),
        "precio_cop_kwh": precio_cop_kwh,
    }


def _precio_del_proyecto(proyecto_id: int, referencia: date) -> float:
    """La tarifa PPA vigente del proyecto ese mes; si no hay, la de referencia.

    Un mantenimiento en una planta con PPA cuesta lo que dice su contrato, no un
    precio genérico. Las tarifas PPA se guardan en COP/kWh.
    """
    tarifa = (
        ppa_models.PpaTarifa.objects
        .filter(
            contrato__proyectos_vinculados__proyecto_id=proyecto_id,
            tarifa__isnull=False,
            **{"año": referencia.year, "mes": referencia.month},
        )
        .values_list("tarifa", flat=True).first()
    )
    return float(tarifa) if tarifa is not None else PRECIO_ENERGIA_COP_KWH


def _generacion_de_la_ventana(proyecto_id: int, desde: date, hasta: date):
    """`(esperada, real)` sumando `generacion_diaria`, ambos días inclusive."""
    totales = py_models.GeneracionDiaria.objects.filter(
        proyecto_id=proyecto_id, fecha__gte=desde, fecha__lte=hasta
    ).aggregate(esperada=Sum("kwh_p90"), real=Sum("kwh_real"))
    return _float(totales["esperada"]), _float(totales["real"])


def _a_fecha(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def calcular(proyecto_id: int, inicio, fin,
             esperada: float | None = None, real: float | None = None) -> dict:
    """Las métricas del evento.

    Si `esperada` o `real` vienen explícitas se RESPETAN —es entrada manual—;
    lo que falte se deriva del histórico de `generacion_diaria` en la ventana.
    """
    desde, hasta = _a_fecha(inicio), _a_fecha(fin)

    if esperada is None or real is None:
        del_historico = _generacion_de_la_ventana(proyecto_id, desde, hasta)
        esperada = esperada if esperada is not None else del_historico[0]
        real = real if real is not None else del_historico[1]

    return metricas(
        esperada, real, precio_cop_kwh=_precio_del_proyecto(proyecto_id, desde)
    )


def aplicar(impacto) -> list[str]:
    """Recalcula y asigna las métricas sobre la instancia. Devuelve los campos."""
    resultado = calcular(
        impacto.proyecto_id, impacto.start_time, impacto.end_time,
        _float(impacto.expected_generation_kwh),
        _float(impacto.actual_generation_kwh),
    )
    campos = [
        "expected_generation_kwh", "actual_generation_kwh", "lost_energy_kwh",
        "financial_impact_cop", "ppa_penalty_risk_flag",
    ]
    for campo in campos:
        setattr(impacto, campo, resultado[campo])
    return campos
