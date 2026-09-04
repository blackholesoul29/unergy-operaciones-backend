"""Emparejar un nombre de proyecto externo con el registro en `proyectos`.

Los nombres llegan de Excel, del sistema de fallas y de webhooks, y nunca vienen
exactamente como están en la base.

Dos pasos, en este orden:

1. **Exacto normalizado** (sin tildes, sin mayúsculas) sobre `nombre_comercial`.
2. **Solapamiento de tokens + similitud**, con desambiguación — el algoritmo
   está en `apps/comun/nombre_matching.py` y lo comparten varios módulos.

El exacto va primero a propósito: el difuso puede preferir otro candidato con
más tokens en común aunque exista uno idéntico.
"""

from apps.comun.nombre_matching import mejor_candidato, normalizar


def _nombres_de(proyecto) -> list[str]:
    return [proyecto.nombre_comercial] if proyecto.nombre_comercial else []


def buscar_por_nombre(nombre_externo: str):
    """El proyecto que mejor coincide, o `None`."""
    if not nombre_externo or not nombre_externo.strip():
        return None

    from apps.proyectos import models as py_models

    proyectos = list(py_models.Proyecto.objects.all())
    objetivo = normalizar(nombre_externo)

    for proyecto in proyectos:
        for nombre in _nombres_de(proyecto):
            if normalizar(nombre) == objetivo:
                return proyecto

    ganador, _score = mejor_candidato(
        nombre_externo, [(p, _nombres_de(p)) for p in proyectos]
    )
    return ganador
