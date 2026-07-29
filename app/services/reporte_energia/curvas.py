"""Curva horaria de medidor (nodo de monitoreo en Quoia) -- generación (eae)
y consumo (iae) del mismo medidor físico.

Puerto de process/src/internals/medidores.py (repo Reporte-Energia), usando
el GaiaClient ya existente del backend en vez de un cliente propio.
"""
from __future__ import annotations

import logging

import pandas as pd

from app.services.mgs.gaia_client import GaiaClient
from app.services.reporte_energia import recuperacion

logger = logging.getLogger("reporte_energia.curvas")

HORAS = list(range(24))

UMBRAL_GENERACION_KWH = 0.5   # kWh por hora mínimo para considerar la hora "generando"
HORA_MINIMA_CIERRE    = 18    # el medidor debe seguir reportando al menos hasta esta hora
HORA_MAXIMA_APERTURA  = 6     # el medidor debe empezar a reportar a más tardar a esta hora

# Nodos cuyo firmware reporta eaepd/iaepd en Wh en vez de kWh -- vacío hasta
# encontrar un caso real (mismo criterio ya usado en Reporte-Energia).
EAE_WH_NODES: frozenset[int] = frozenset()

_CAMPOS_POR_VAR = {
    "eae": ("eaepd1", "eaepd2", "eaepd3"),
    "iae": ("iaepd1", "iaepd2", "iaepd3"),
}


def construir_mapa_medidor_nodo(gaia: GaiaClient) -> dict[int, int]:
    """meter_id -> node_id, desde /api/node/retailer/ (gaia.get_all_nodes()).

    main_meter/backup_meter de un border de Quoia son IDs administrativos de
    medidor; el endpoint de mediciones usa node_id, un espacio de IDs
    distinto -- este mapa es la conversión, igual que
    process/src/internals/nodos_quoia.py en Reporte-Energia.
    """
    mapa: dict[int, int] = {}
    for node in gaia.get_all_nodes():
        meter = node.get("meter") or {}
        nid = node.get("id")
        mid = meter.get("id") if isinstance(meter, dict) else None
        if mid is not None and nid is not None:
            mapa[int(mid)] = int(nid)
    return mapa


def _horas_reportadas(filas: list[dict]) -> set[int]:
    """Horas (0-23) para las que llegó al menos una fila en la respuesta de la API,
    sin importar su valor — permite distinguir 'no generó' de 'no reportó'."""
    horas = set()
    for fila in filas:
        ts = fila.get("time", "")
        try:
            hora = int(ts[11:13])
        except (ValueError, IndexError):
            continue
        if 0 <= hora < 24:
            horas.add(hora)
    return horas


def dia_completo(curva: pd.Series, horas_con_dato: set[int]) -> bool:
    """True si no hay huecos de reporte dentro de la ventana real de generación.

    Revisa huecos en ambos extremos del día -- que el medidor haya empezado a
    reportar a más tardar a HORA_MAXIMA_APERTURA y que haya seguido hasta al
    menos HORA_MINIMA_CIERRE -- antes de solo mirar gaps DENTRO de la ventana
    de generación detectada (una hora sin sol nunca es un hueco, así que solo
    mirar gaps internos no detecta un medidor que nunca empezó a reportar o
    que dejó de reportar antes de tiempo).
    """
    horas_generando = [h for h, v in curva.items() if pd.notna(v) and v > UMBRAL_GENERACION_KWH]
    if not horas_generando:
        return False  # no generó nada ese día -- no es este chequeo el que decide (ver Caso 6)

    if max(horas_con_dato, default=-1) < HORA_MINIMA_CIERRE:
        return False  # el medidor dejó de reportar temprano

    if min(horas_con_dato, default=24) > HORA_MAXIMA_APERTURA:
        return False  # el medidor empezó a reportar demasiado tarde

    inicio, fin = min(horas_generando), max(horas_generando)
    return all(h in horas_con_dato for h in range(inicio, fin + 1))


def _curva_de_mediciones(filas: list[dict], node_id: int, campos: tuple[str, str, str]) -> pd.Series:
    """Convierte lista de mediciones de nodo -> pd.Series[0..23] kWh por hora.

    Las horas sin NINGUNA fila real quedan en NaN, no 0.0 -- un hueco de
    telemetría (el medidor dejó de reportar) es indistinguible de "generó/
    consumió cero" si se inicializa todo en 0.0 de entrada.
    """
    en_wh = node_id in EAE_WH_NODES
    acum = {h: 0.0 for h in HORAS}
    horas_con_dato = set()
    for fila in filas:
        ts = fila.get("time", "")
        try:
            hora = int(ts[11:13])
        except (ValueError, IndexError):
            continue
        if not (0 <= hora < 24):
            continue
        valor = sum(float(fila.get(f, 0) or 0) for f in campos)
        acum[hora] += valor / 1000 if en_wh else valor
        horas_con_dato.add(hora)
    curva = pd.Series(acum, dtype=float)
    for h in HORAS:
        if h not in horas_con_dato:
            curva[h] = None
    return curva


def _curva_nodo(
    gaia: GaiaClient, node_id: int | None, fecha_str: str, label: str, var_name: str = "eae",
) -> tuple[pd.Series, bool]:
    """Retorna (curva horaria kWh, dia_completo) para un node_id.

    var_name: 'eae' (generación, por defecto) o 'iae' (consumo).
    Serie de None×24 y completo=False si no hay nodo o no hay datos.
    """
    vacia = pd.Series([None] * 24, index=HORAS, dtype=float)
    if node_id is None:
        return vacia, False
    filas = gaia.get_node_measurements(node_id, fecha_str, var_name)
    if not filas:
        return vacia, False
    curva = _curva_de_mediciones(filas, node_id, _CAMPOS_POR_VAR[var_name])
    completo = dia_completo(curva, _horas_reportadas(filas))
    return curva, completo


def recuperar_y_releer(
    gaia: GaiaClient, node_id: int, meter_id: int, fecha_str: str, label: str, var_name: str = "eae",
) -> tuple[pd.Series, bool, bool]:
    """Interroga el medidor (recuperación activa vía WebSocket) y vuelve a
    leer su curva desde Quoia.

    Solo tiene sentido llamarla cuando la lectura pasiva ya salió
    incompleta -- recuperar un medidor ya completo no cambia nada.

    Retorna (curva, completo, exito) -- 'exito' es si Quoia confirmó
    'status': 'success' en la interrogación (no si el día quedó completo
    después, eso ya lo dice 'completo')."""
    resultado = recuperacion.recuperar_datos_medidor(meter_id, fecha_str, fecha_str)
    exito = recuperacion.fue_exitosa(resultado)
    if not exito:
        logger.info("recuperacion %s meter_id=%s no confirmó éxito: %s", label, meter_id, resultado)
    curva, completo = _curva_nodo(gaia, node_id, fecha_str, f"{label} (post-recuperacion)", var_name)
    return curva, completo, exito


def curvas_de_frontera(
    gaia: GaiaClient,
    mapa_medidor_nodo: dict[int, int],
    main_meter_id: int | None,
    backup_meter_id: int | None,
    fecha_str: str,
    frt_code: str,
    recuperar: bool = True,
) -> dict:
    """Curvas horarias (kWh) de generación (eae) y consumo propio (iae) del
    medidor principal y de respaldo de una frontera, para una fecha.

    'Consumo propio' acá es el autoconsumo del medidor de GENERACIÓN (equipos
    tomando de red en horas de bajo sol) -- no es una frontera de consumo
    aparte, es el mismo medidor, otra variable (iae en vez de eae).

    Si `recuperar` es True (default) y la lectura pasiva de un medidor sale
    incompleta en CUALQUIERA de sus dos variables (eae o iae), se interroga
    ese medidor UNA sola vez -- la interrogación reenvía todas las lecturas
    del dispositivo físico sin importar la variable, así que no hace falta
    interrogar dos veces el mismo medidor -- y se vuelven a leer ambas
    curvas (eae e iae) después.
    """
    node_p = mapa_medidor_nodo.get(int(main_meter_id)) if main_meter_id else None
    node_r = mapa_medidor_nodo.get(int(backup_meter_id)) if backup_meter_id else None

    curva_p, comp_p = _curva_nodo(gaia, node_p, fecha_str, f"{frt_code}/principal", "eae")
    curva_r, comp_r = _curva_nodo(gaia, node_r, fecha_str, f"{frt_code}/respaldo", "eae")
    cons_p, cons_comp_p = _curva_nodo(gaia, node_p, fecha_str, f"{frt_code}/principal/consumo", "iae")
    cons_r, cons_comp_r = _curva_nodo(gaia, node_r, fecha_str, f"{frt_code}/respaldo/consumo", "iae")

    intentos: list[str] = []
    if recuperar:
        if node_p is not None and main_meter_id and not (comp_p and cons_comp_p):
            curva_p, comp_p, exito = recuperar_y_releer(gaia, node_p, int(main_meter_id), fecha_str, f"{frt_code}/principal", "eae")
            cons_p, cons_comp_p, _ = recuperar_y_releer(gaia, node_p, int(main_meter_id), fecha_str, f"{frt_code}/principal/consumo", "iae")
            intentos.append(f"principal: {'éxito' if exito else 'falló'}")
        if node_r is not None and backup_meter_id and not (comp_r and cons_comp_r):
            curva_r, comp_r, exito = recuperar_y_releer(gaia, node_r, int(backup_meter_id), fecha_str, f"{frt_code}/respaldo", "eae")
            cons_r, cons_comp_r, _ = recuperar_y_releer(gaia, node_r, int(backup_meter_id), fecha_str, f"{frt_code}/respaldo/consumo", "iae")
            intentos.append(f"respaldo: {'éxito' if exito else 'falló'}")

    return {
        "node_ppal": node_p, "node_resp": node_r,
        "curva_ppal": curva_p, "curva_resp": curva_r,
        "ppal_completo": comp_p, "resp_completo": comp_r,
        "consumo_ppal": cons_p, "consumo_resp": cons_r,
        "consumo_ppal_completo": cons_comp_p, "consumo_resp_completo": cons_comp_r,
        "recuperacion_datos": ", ".join(intentos) or None,
    }
