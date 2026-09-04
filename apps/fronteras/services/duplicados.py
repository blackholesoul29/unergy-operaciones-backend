"""Detección de fronteras con nombre parecido.

Mismo algoritmo difuso que proyectos y operadores (`apps/comun/nombre_matching`):
detecta parecidos aunque no sea un caso de «un nombre contenido en el otro»
— por ejemplo «AGGE Extractora Monterrey» contra «AGGE Frontera Monterrey».

Deliberadamente permisivo: **no bloquea, solo avisa** y el cliente reintenta con
`?forzar=true`.
"""

from apps.comun.nombre_matching import mejor_candidato
from apps.fronteras import models as fr_models


def parecida(nombre: str | None, tipo: str | None = None, excluir_id=None):
    """Una frontera viva con nombre parecido, o `None`.

    Con `tipo` solo compara dentro del MISMO tipo: reduce los falsos positivos
    entre fronteras de naturaleza distinta —generación contra consumo— que
    comparten palabras en el nombre.

    `excluir_id` evita que una frontera se compare consigo misma al editarla:
    su nombre actual siempre «empataría» con el nuevo si no cambió.
    """
    if not nombre:
        return None

    # Solo id y nombre: traer las 40 columnas de cada candidata para un chequeo
    # que corre en cada create, update y confirmar es trabajo sin uso.
    consulta = fr_models.Frontera.objects.filter(deleted_at__isnull=True)
    if tipo:
        consulta = consulta.filter(tipo_frontera=tipo)
    if excluir_id is not None:
        consulta = consulta.exclude(pk=excluir_id)

    candidatos = [
        (fila, [fila["nombre_frontera"]])
        for fila in consulta.values("id", "nombre_frontera")
    ]
    encontrada, _score = mejor_candidato(nombre, candidatos)
    return encontrada


def aviso(duplicado) -> dict:
    """El cuerpo del 409, con las mismas claves que proyectos y operadores."""
    return {
        "mensaje": (
            f"Ya existe una frontera con un nombre muy parecido: "
            f'\'{duplicado["nombre_frontera"]}\' (ID {duplicado["id"]}).'
        ),
        "duplicado_nombre": True,
        "candidato_id": duplicado["id"],
        "candidato_nombre": duplicado["nombre_frontera"],
    }
