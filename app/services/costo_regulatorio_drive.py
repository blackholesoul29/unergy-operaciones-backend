"""Ingesta del costo regulatorio del mes desde el Drive de Estados de Resultados.

Reutiliza el plumbing de `app/services/drive.py` (listar la carpeta de ER, parsear el
nombre, bajar el archivo) y el parser de `app/services/costo_regulatorio.py`. La
selección de período/versión es pura; `costo_regulatorio_del_mes` inyecta las funciones
de Drive para poder testear sin red.

Regla: para (año, mes) se toma el `Cruce facturas` de ESE período con la versión más
definitiva (txf > txN por número). Si no existe, fallback al último período disponible
que no sea posterior al pedido ("último disponible").
"""
from __future__ import annotations


def _rank_version(version) -> int:
    """txf es la final (más alta); txN vale N; desconocida cae al fondo."""
    v = str(version or "").strip().lower()
    if v == "txf":
        return 1000
    if v.startswith("tx"):
        try:
            return int(v[2:])
        except ValueError:
            return -1
    return -1


def seleccionar_cruce(cruces: list[dict], anio: int, mes: int) -> dict | None:
    """cruces = [{'id','anio','mes','version'}, ...] -> el cruce elegido con flag
    'fallback', o None si no hay ninguno.

    Elige el período == (anio, mes); si no hay, el mayor período <= (anio, mes). Dentro
    del período, la versión de mayor rank.
    """
    con_periodo = [c for c in cruces if c.get("anio") and c.get("mes")]
    if not con_periodo:
        return None
    objetivo = (anio, mes)
    exactos = [c for c in con_periodo if (c["anio"], c["mes"]) == objetivo]
    if exactos:
        elegido = max(exactos, key=lambda c: _rank_version(c["version"]))
        return {**elegido, "fallback": False}
    previos = [c for c in con_periodo if (c["anio"], c["mes"]) <= objetivo]
    if not previos:
        return None
    ultimo_periodo = max((c["anio"], c["mes"]) for c in previos)
    candidatos = [c for c in previos if (c["anio"], c["mes"]) == ultimo_periodo]
    elegido = max(candidatos, key=lambda c: _rank_version(c["version"]))
    return {**elegido, "fallback": True}
