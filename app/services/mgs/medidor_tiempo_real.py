"""Lectura del medidor de frontera para la vista de Generación Solar.

Se piden dos variables al nodo, por el mismo método que usa el pipeline del
ASIC (`GaiaClient.get_node_measurements`):

  · `ap`  -- potencia activa. Es la curva del día y, su última lectura, la
             potencia de ahora.
  · `eae` -- energía activa exportada. Sumada, es el total del día.

Reemplaza a `GaiaClient.get_node_electrical_snapshot()` en este uso, que pedía
las 8 familias de variables del nodo (v, c, ap, rp, pf, eae, iae, ere) -- y
como la tarjeta lo hacía para principal Y respaldo, eran hasta 16 llamadas
externas por proyecto para dibujar dos líneas.

Solo se corrigen dos cosas de los datos crudos, ambas verificadas contra
Quoia el 2026-09-03 y ambas necesarias:

  · **El signo.** Hay medidores que reportan la generación en negativo (nodo
    1731: -721,7 kW a las 09:45). Es polaridad de CT invertida en sitio, no
    consumo.
  · **La unidad.** Unos nodos entregan vatios y otros kilovatios, y conviven:
    de 6 nodos con dato ese día, 603 y 883 rondaban 1.050.000 (vatios) y 1731
    marcaba 726,6 (kilovatios). No hay campo que lo declare, así que se deduce
    contra la capacidad instalada de la planta.

    No es un hallazgo nuevo: reporte_energia/datos_crudos.py ya lo documenta
    como "un error CRÓNICO de escala de unidad (ej. Polaris 1/2, ~1.150x, un
    nodo que reporta en W en vez de kW)". La diferencia es qué se hace con
    esas lecturas. El pipeline las DESCARTA -- para el ASIC un valor mal
    escalado es inservible y conviene caer a otra fuente. Acá se CONVIERTEN,
    porque esta vista no reporta a nadie y descartarlas dejaría la gráfica de
    medidores vacía para la mitad de los nodos.

Lo que a propósito NO se hace, y por qué:

  · **No se rellenan los huecos.** El compuesto reconstruye potencia a partir
    de los deltas del contador cuando `ap` lleva rato sin reportar, y la
    dibuja igual que una medición real. Eso no protege ningún número -- la
    energía del día sale del contador, no de integrar la curva -- así que
    solo maquilla la gráfica, y en una vista de tiempo real inventa un
    detalle que no existe. Acá el hueco se ve.
  · **No se filtran las filas `recovered`.** El pipeline del ASIC sí lo hace,
    pero porque integra la curva por Riemann y un cero sintético le distorsiona
    la energía. Acá solo se dibujan puntos, así que esa razón no aplica.
"""
from __future__ import annotations

_FASES_AP = ("app1", "app2", "app3")
_FASES_EAE = ("eaepd1", "eaepd2", "eaepd3")

# Cuánto puede superar una lectura a la capacidad de su propia planta antes de
# que la única explicación sea que viene en vatios. Un medidor no entrega 10x
# lo que la planta puede producir.
_FACTOR_VATIOS = 10.0

# Sin capacidad instalada con qué comparar: para una minigranja, un valor así
# solo tiene sentido en vatios.
_TECHO_KW_SIN_CAPACIDAD = 5000.0


def _suma(fila: dict, fases: tuple[str, ...]) -> float:
    return sum(float(fila.get(f) or 0) for f in fases)


def snapshot_medidor(
    gaia,
    node_id: int | None,
    fecha_str: str,
    capacidad_efectiva_mw: float | None = None,
) -> dict | None:
    """Potencia y energía del día de un nodo. None si no hay nodo.

    Si el nodo existe pero no reportó, devuelve la estructura con la curva
    vacía: "el medidor no reportó" es un dato, distinto de "no hay medidor".
    """
    if not gaia or not node_id:
        return None

    filas_ap = gaia.get_node_measurements(node_id, fecha_str, "ap") or []
    filas_eae = gaia.get_node_measurements(node_id, fecha_str, "eae") or []

    crudos = [(f["time"], abs(_suma(f, _FASES_AP))) for f in filas_ap if f.get("time")]
    techo = (capacidad_efectiva_mw * 1000 * _FACTOR_VATIOS
             if capacidad_efectiva_mw else _TECHO_KW_SIN_CAPACIDAD)
    divisor = 1000.0 if max((kw for _, kw in crudos), default=0.0) > techo else 1.0

    curva = sorted(
        ({"time": t, "kw": round(kw / divisor, 3)} for t, kw in crudos),
        key=lambda p: p["time"],
    )
    energia = sum(_suma(f, _FASES_EAE) for f in filas_eae) if filas_eae else None
    # El contador se reporta en intervalos mas largos que la potencia, asi que
    # el acumulado puede ir hasta media hora por detras del numero de "ahora".
    # Se expone hasta cuando cubre para poder decirlo, en vez de dar a entender
    # que es del ultimo instante.
    energia_hasta = max((f["time"] for f in filas_eae if f.get("time")), default=None)

    return {
        "node_id": node_id,
        "potencia_kw": curva[-1]["kw"] if curva else None,
        "ultima_lectura": curva[-1]["time"] if curva else None,
        "energia_kwh": round(energia, 3) if energia is not None else None,
        "energia_hasta": energia_hasta,
        "curva": curva,
    }


def elegir_medidor(principal: dict | None, respaldo: dict | None) -> tuple[dict | None, str | None]:
    """El principal, y si no trajo dato, el respaldo.

    La decisión vive SOLO acá: el frontend la recibe resuelta. Antes el mismo
    criterio estaba escrito también en SolarLiveView.vue y podían
    desincronizarse en silencio -- la gráfica mostrando un medidor y el resto
    de la tarjeta hablando de otro.

    A propósito no se compara cuál midió más: preferir "el de mayor valor" es
    lo que el clasificador de Consumo tuvo que descartar en julio, porque un
    hueco de telemetría acumula horas sin reportar en un pico artificial y el
    medidor inflado gana siempre (Chiriguaná Norte 1).
    """
    if principal and principal["curva"]:
        return principal, "principal"
    if respaldo and respaldo["curva"]:
        return respaldo, "respaldo"
    if principal:
        return principal, "principal"
    return (respaldo, "respaldo") if respaldo else (None, None)
