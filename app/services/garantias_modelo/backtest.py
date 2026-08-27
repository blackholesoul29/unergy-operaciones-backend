"""Métricas del backtest, puras.

Se reporta el error **por componente**, no solo del total: así se sabe qué pieza falla
en vez de saber únicamente que el total no cuadra.
"""
from __future__ import annotations

import statistics as st

# Enteros a propósito donde el umbral es entero: la clave se arma con `str(u)`, y un
# `1.0` produciría `dentro_1_0` en vez de `dentro_1`.
UMBRALES = (0.01, 1, 5)


def _clave(umbral) -> str:
    return f"dentro_{str(umbral).replace('.', '_')}"


def error_relativo(*, predicho: float, real: float) -> float | None:
    """Error porcentual absoluto. `None` cuando el real es cero.

    No se devuelve infinito ni un número enorme: la exposición neta es un residuo
    pequeño de números grandes, así que cerca de cero cualquier diferencia mínima da un
    porcentaje absurdo que contamina la mediana. Un real de cero no es comparable en
    porcentaje y se reporta aparte.
    """
    if not real:
        return None
    return abs(predicho - real) / abs(real) * 100.0


def resumen_error(errores: list[float | None]) -> dict:
    """Mediana, percentiles y conteos por umbral. Los `None` se descartan y no cuentan."""
    v = sorted(e for e in errores if e is not None)
    if not v:
        return {"n": 0, "mediana": None, "p90": None, "max": None,
                **{_clave(u): 0 for u in UMBRALES}}
    return {
        "n": len(v),
        "mediana": st.median(v),
        "p90": v[min(len(v) - 1, int(len(v) * 0.9))],
        "max": max(v),
        **{_clave(u): sum(1 for x in v if x < u) for u in UMBRALES},
    }
