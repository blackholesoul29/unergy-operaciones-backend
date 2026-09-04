"""Lectura del medidor de frontera para la vista de Generación Solar
(potencia en tiempo real), por el mismo camino que usa el pipeline del ASIC.

Reemplaza a `GaiaClient.get_node_electrical_snapshot()` para este uso. El
compuesto pide las 8 familias de variables del nodo (v, c, ap, rp, pf, eae,
iae, ere) y la tarjeta lo hacía para principal Y respaldo -- hasta 16 llamadas
externas por proyecto para dibujar dos líneas. Acá se piden las dos que la
vista necesita: `ap` para la potencia y `eae` para la energía del día.

Diferencias deliberadas con el compuesto, todas discutidas con la usuaria el
2026-09-03:

  · **Se filtran las filas `recovered`.** Son marcadores sintéticos que Quoia
    inserta en 0.0 justo antes de la lectura real (ver
    reporte_energia/datos_crudos.py, donde este mismo filtro evitó multiplicar
    la energía por ~70x en un intervalo). El compuesto no los filtra.
  · **No se rellenan huecos con potencia derivada del contador.** El compuesto
    reconstruye kW a partir de los deltas de `eae` cuando `ap` lleva más de 30
    min sin reportar, y los dibuja idénticos a una medición real. Eso no
    protege ningún número -- la energía del día sale del contador, no de
    integrar la curva -- así que solo maquilla la curva, y en una vista de
    tiempo real fabrica un detalle que no existe. Acá el hueco se ve, y
    `ultima_lectura` dice desde cuándo.
  · **La unidad no se adivina por magnitud.** El compuesto asume vatios si
    algún valor pasa de 5000, lo que falla para plantas de más de 5 MW. Acá se
    compara contra la capacidad instalada, que es un dato que sí tenemos.

Se conserva el valor absoluto del compuesto: hay medidores que reportan la
generación en negativo (verificado en vivo, nodo 1731: -721,7 kW a las 09:45),
que es polaridad de CT invertida en sitio y no consumo real.
"""
from __future__ import annotations

import logging

from app.services.reporte_energia.utils import limite_plausible_kwh

logger = logging.getLogger("mgs.medidor_tiempo_real")

_FASES_AP = ("app1", "app2", "app3")
_FASES_EAE = ("eaepd1", "eaepd2", "eaepd3")

# Cuántas veces la capacidad instalada tiene que superar una lectura para
# concluir que viene en vatios y no en kilovatios. Un medidor no puede
# entregar 10x la capacidad de su propia planta, así que un factor de 10 ya
# es inequívoco -- y deja margen de sobra para los picos legítimos.
_FACTOR_SOSPECHA_VATIOS = 10.0

# Sin capacidad instalada no hay contra qué comparar, así que se cae al
# criterio del compuesto: valores absurdos para kW en una minigranja.
_UMBRAL_VATIOS_SIN_CAPACIDAD = 5000.0


def _suma_fases(fila: dict, fases: tuple[str, ...]) -> float:
    return sum(float(fila.get(f) or 0) for f in fases)


def _divisor_unidad(maximo: float, capacidad_kw: float | None) -> float:
    """1000 si las lecturas vienen en vatios, 1 si ya vienen en kilovatios."""
    if capacidad_kw and capacidad_kw > 0:
        return 1000.0 if maximo > capacidad_kw * _FACTOR_SOSPECHA_VATIOS else 1.0
    return 1000.0 if maximo > _UMBRAL_VATIOS_SIN_CAPACIDAD else 1.0


def snapshot_medidor(
    gaia,
    node_id: int | None,
    fecha_str: str,
    capacidad_efectiva_mw: float | None = None,
) -> dict | None:
    """Potencia y energía del día de un nodo, para la vista en tiempo real.

    Retorna None si no hay nodo. Si el nodo existe pero no trajo nada, retorna
    la estructura con la curva vacía -- "el medidor no reportó" es un dato,
    distinto de "no hay medidor".

        {
          "node_id":         int,
          "potencia_kw":     float | None,   # la última lectura real = "ahora"
          "ultima_lectura":  str | None,     # su timestamp, para la frescura
          "energia_kwh":     float | None,   # total del día, del contador
          "curva":           [{"time": str, "kw": float}],  # sin rellenar
          "lecturas":        int,            # puntos reales de ap
          "descartadas":     int,            # marcadores + implausibles
        }
    """
    if not gaia or not node_id:
        return None

    filas_ap = gaia.get_node_measurements(node_id, fecha_str, "ap") or []
    filas_eae = gaia.get_node_measurements(node_id, fecha_str, "eae") or []

    # Marcadores sintéticos de Quoia: siempre en 0.0, insertados segundos
    # antes de la lectura real. No son mediciones.
    reales = [f for f in filas_ap if not f.get("recovered") and f.get("time")]
    descartadas = len(filas_ap) - len(reales)

    crudos = [(f["time"], abs(_suma_fases(f, _FASES_AP))) for f in reales]
    maximo = max((kw for _, kw in crudos), default=0.0)
    capacidad_kw = (capacidad_efectiva_mw or 0) * 1000 or None
    divisor = _divisor_unidad(maximo, capacidad_kw)

    limite = limite_plausible_kwh(capacidad_efectiva_mw)
    curva: list[dict] = []
    for ts, kw_crudo in crudos:
        kw = round(kw_crudo / divisor, 3)
        if limite is not None and kw > limite:
            descartadas += 1
            continue
        curva.append({"time": ts, "kw": kw})
    curva.sort(key=lambda p: p["time"])

    if descartadas:
        logger.info(
            "medidor nodo %s: %d lecturas usadas, %d descartadas (marcadores o implausibles)",
            node_id, len(curva), descartadas,
        )

    # El contador de energía se suma completo: es el total del día y no
    # depende de que la curva de potencia esté completa.
    energia = sum(_suma_fases(f, _FASES_EAE) for f in filas_eae) if filas_eae else None

    return {
        "node_id": node_id,
        "potencia_kw": curva[-1]["kw"] if curva else None,
        "ultima_lectura": curva[-1]["time"] if curva else None,
        "energia_kwh": round(energia, 3) if energia is not None else None,
        "curva": curva,
        "lecturas": len(curva),
        "descartadas": descartadas,
    }


def elegir_medidor(snap_principal: dict | None, snap_respaldo: dict | None) -> tuple[dict | None, str | None]:
    """(snapshot, 'principal'|'respaldo') del medidor que se muestra.

    Criterio: **el que tenga más lecturas reales**, no el de mayor energía.
    "Mayor valor" es justo lo que el clasificador de Consumo descartó en julio
    (Chiriguaná Norte 1: un hueco de telemetría acumuló 9 horas sin reportar
    en un pico artificial, y "mayor valor" elegía sistemáticamente el medidor
    más inflado). Acá la pregunta no es cuál midió más, es cuál está
    reportando mejor -- que para una vista de tiempo real es lo que importa.

    Esta decisión vive SOLO acá. El frontend la recibe resuelta y no la vuelve
    a calcular, que era el otro problema: el mismo criterio estaba escrito en
    los dos lados y podían desincronizarse en silencio.
    """
    if not snap_principal and not snap_respaldo:
        return None, None
    if not snap_respaldo:
        return snap_principal, "principal"
    if not snap_principal:
        return snap_respaldo, "respaldo"
    if snap_respaldo["lecturas"] > snap_principal["lecturas"]:
        return snap_respaldo, "respaldo"
    # Empate -> principal, que es el medidor de liquidación.
    return snap_principal, "principal"
