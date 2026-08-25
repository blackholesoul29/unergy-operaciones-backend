"""Helpers compartidos por los módulos del pipeline de reporte de energía."""
from __future__ import annotations

import pandas as pd

HORAS = list(range(24))

# Ventanas horarias para el relleno horario centralizado (ver
# reconectador.rellenar_horas_faltantes) -- fuera de estas horas la
# generación real esperada es ~0, así que rellenar ahí no aporta nada y solo
# arriesga meter ruido de telemetría nocturna como si fuera dato real.
HORAS_SOLARES = range(6, 18)        # 6am a 6pm -- Solenium×FP e histórico
HORAS_RECONECTADOR = range(7, 17)   # 7am a 5pm -- más angosta: es la primera
                                     # fuente que se intenta y la menos
                                     # verificable (dato físico crudo, sin
                                     # cruzarlo contra nada más en ese momento)

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


def rellenar_con_otro_medidor(
    curva: pd.Series, medidor_usado: str | None,
    curva_principal: list[float | None] | None, curva_respaldo: list[float | None] | None,
) -> tuple[pd.Series, set[int]]:
    """Rellena los huecos de `curva` con el OTRO medidor (el que NO ganó
    como medidor_usado), para las mismas horas -- mismo consumo/generación
    física, otro canal de lectura (ver MGS 0021 Ibirico Consumo
    2026-08-11: medidor respaldo usado sin dato a las 4h, pero principal sí
    la tenía). No es una estimación como histórico/Solenium/reconectador --
    es dato real de un medidor, así que es la PRIMERA fuente a intentar en
    la acción manual 'Rellenar horas' (Generación y Consumo), antes de
    reconectador/Solenium×FP/histórico.

    Retorna (curva_rellenada, horas_rellenadas)."""
    if not curva.isna().any():
        return curva, set()
    mu = medidor_usado or ""
    if mu.startswith("principal"):
        otra = curva_respaldo
    elif mu.startswith("respaldo"):
        otra = curva_principal
    else:
        otra = None
    if otra is None:
        return curva, set()

    curva_otro = lista_a_curva(otra)
    curva = curva.copy()
    horas: set[int] = set()
    for h in list(curva[curva.isna()].index):
        valor = curva_otro.get(h)
        if pd.notna(valor):
            curva[h] = valor
            horas.add(h)
    return curva, horas
