"""Calculo de avance de un registro. Portado de src/lib/domain/avance.py.

    avance_pct = suma de peso_pct de los hitos COMPLETADOS

Un hito "en proceso" no suma; solo puntuan los completados (evita avances inflados).
Los pesos llegan desde HitoProyecto.peso_pct (configurables); aqui no se asume ninguno.
Funciones puras (sin dependencia de la sesion DB).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.registros_cnd.services.dominio import (
    ETAPAS_ACTUALES, HITOS, HITOS_POR_KEY,
)


@dataclass
class HitoAvance:
    hito: str
    peso_pct: float
    completado: bool


def redondear2(n: float) -> float:
    """Redondea a 2 decimales."""
    return round(n + 1e-12, 2)


def hitos_por_defecto() -> list[HitoAvance]:
    """Plantilla inicial de hitos (todos incompletos) con los pesos por defecto."""
    return [HitoAvance(hito=h["key"], peso_pct=h["peso_default"], completado=False) for h in HITOS]


def calcular_avance_pct(hitos: list[HitoAvance]) -> float:
    """Suma de los pesos de los hitos completados = avance total (%)."""
    return redondear2(sum(h.peso_pct for h in hitos if h.completado))


def suma_pesos(hitos: list[HitoAvance]) -> float:
    """Suma de TODOS los pesos (deberia ser 100 con la plantilla por defecto)."""
    return redondear2(sum(h.peso_pct for h in hitos))


@dataclass
class AvanceEtapa:
    etapa: str
    ganado_pct: float
    total_pct: float
    completos: int
    total_hitos: int


def avance_por_etapa(hitos: list[HitoAvance]) -> list[AvanceEtapa]:
    """Desglose de avance por etapa (solo etapas con hitos = alcance actual)."""
    acc: dict[str, AvanceEtapa] = {
        etapa: AvanceEtapa(etapa=etapa, ganado_pct=0.0, total_pct=0.0, completos=0, total_hitos=0)
        for etapa in ETAPAS_ACTUALES
    }
    for h in hitos:
        meta = HITOS_POR_KEY.get(h.hito)
        if not meta:
            continue
        row = acc.get(meta["etapa"])
        if not row:
            continue
        row.total_pct = redondear2(row.total_pct + h.peso_pct)
        row.total_hitos += 1
        if h.completado:
            row.ganado_pct = redondear2(row.ganado_pct + h.peso_pct)
            row.completos += 1
    return [acc[e] for e in ETAPAS_ACTUALES]


def siguiente_hito_pendiente(hitos: list[HitoAvance]) -> str | None:
    """Siguiente hito pendiente en el orden canonico (1a, 1b, 2a...). None si todo completo."""
    completados = {h.hito for h in hitos if h.completado}
    for meta in HITOS:
        if meta["key"] not in completados:
            return meta["key"]
    return None
