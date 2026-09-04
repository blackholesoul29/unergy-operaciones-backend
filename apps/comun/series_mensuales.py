"""Lectura tolerante de las series mensuales de energía de un proyecto.

`proyectos.p50_mensual_kwh` (y sus hermanas p90/p99) son JSONB con 12 valores,
pero las filas anteriores a esa migración guardan el arreglo como **texto JSON**
dentro del mismo campo. Quien lo lea crudo del ORM recibe a veces una lista y a
veces un string; recorrer el string da caracteres y cualquier `float(v)` revienta
con `could not convert string to float: '['`.

Este helper existe para que nadie más tropiece con eso. La misma normalización ya
vivía duplicada en `app/schemas/proyectos.py::coerce_json_list` (para la respuesta
de la API) y en `app/api/v1/monitoreo.py::_parse_kwh_list`.
"""
import json


def serie_mensual_kwh(valor) -> list[float]:
    """Los valores numéricos de la serie, venga como lista o como texto JSON.

    Devuelve [] cuando no hay nada que leer o el dato es ilegible: quien llama
    decide qué hacer con la ausencia, que nunca es una excepción. Los elementos
    que no son numéricos (None, texto suelto) se descartan uno a uno en vez de
    perder la serie completa.
    """
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return []
    if not isinstance(valor, (list, tuple)):
        return []
    out: list[float] = []
    for v in valor:
        if v is None or isinstance(v, bool):
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out
