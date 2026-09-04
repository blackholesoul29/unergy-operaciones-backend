"""Reglas de negocio de los operadores de red.

La detección de duplicados vive acá y no en la vista porque la usan DOS caminos
(crear y actualizar) y reimplementarla es como se desincronizan: el mismo
nombre pasaría por POST y se rechazaría por PATCH.
"""

from apps.comun.nombre_matching import mejor_candidato
from apps.fronteras import models as fr_models


def duplicado_exacto(nombre_legal: str, excluir_id: int | None = None):
    """Otro operador con el MISMO nombre legal, ignorando mayúsculas.

    Esto sí bloquea: el nombre legal es único en la base.
    """
    consulta = fr_models.OperadorRed.objects.filter(
        nombre_legal__iexact=(nombre_legal or "").strip()
    )
    if excluir_id is not None:
        consulta = consulta.exclude(pk=excluir_id)
    return consulta.first()


def duplicado_parecido(nombre: str, excluir_id: int | None = None):
    """Un operador con nombre PARECIDO, no necesariamente igual.

    Mismo algoritmo que fronteras y proyectos (`apps/comun/nombre_matching.py`).
    Deliberadamente permisivo: no bloquea, solo avisa — el cliente reintenta con
    `?forzar=true` y se crea igual.
    """
    consulta = fr_models.OperadorRed.objects.all()
    if excluir_id is not None:
        consulta = consulta.exclude(pk=excluir_id)
    candidatos = [
        (op, [n for n in (op.nombre_legal, op.nombre_comercial) if n])
        for op in consulta
    ]
    item, _score = mejor_candidato(nombre or "", candidatos)
    return item


def aviso_de_parecido(operador) -> dict:
    """El cuerpo del 409 que ya consume el frontend. Mismas claves, mismo texto."""
    nombre = operador.nombre_comercial or operador.nombre_legal
    return {
        "mensaje": (
            f"Ya existe un operador con un nombre muy parecido: "
            f"'{nombre}' (ID {operador.id})."
        ),
        "duplicado_nombre": True,
        "candidato_id": operador.id,
        "candidato_nombre": nombre,
    }
