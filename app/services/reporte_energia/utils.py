"""Helpers compartidos por los módulos del pipeline de reporte de energía."""
from __future__ import annotations

import pandas as pd

HORAS = list(range(24))

CURVA_CERO: pd.Series = pd.Series({h: 0.0 for h in HORAS}, dtype=float)
CURVA_VACIA: pd.Series = pd.Series({h: None for h in HORAS}, dtype=float)  # sin dato -- no confundir con "generó 0"


def escalar_curva(curva: pd.Series, total_objetivo: float) -> pd.Series:
    """Escala una curva horaria al total objetivo manteniendo la distribución."""
    total_actual = curva.fillna(0).sum()
    if total_actual == 0:
        return CURVA_CERO.copy()
    factor = total_objetivo / total_actual
    return (curva.fillna(0) * factor).round(4)


def escalar_curva_con_huecos(curva: pd.Series, total_objetivo: float) -> pd.Series:
    """Igual que escalar_curva, pero preserva NaN en las horas sin dato en vez
    de taparlas con 0 -- para que sigan siendo candidatas al relleno horario
    centralizado (reconectador -> Solenium -> histórico)."""
    total_actual = curva.fillna(0).sum()
    if total_actual == 0:
        return curva.where(curva.isna(), 0.0)
    factor = total_objetivo / total_actual
    return (curva * factor).round(4)


def curva_a_lista(curva: pd.Series | None) -> list[float | None] | None:
    """Serializa una pd.Series[0..23] a una lista JSON-friendly (para JSONB)."""
    if curva is None:
        return None
    return [None if pd.isna(curva.get(h)) else round(float(curva[h]), 4) for h in HORAS]


def lista_a_curva(valores: list[float | None] | None) -> pd.Series:
    """Deserializa una lista JSONB de 24 valores a pd.Series[0..23]."""
    if not valores:
        return CURVA_VACIA.copy()
    return pd.Series({h: valores[h] if h < len(valores) else None for h in HORAS}, dtype=float)
