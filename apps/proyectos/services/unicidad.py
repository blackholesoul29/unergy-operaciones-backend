"""Las dos validaciones que protegen la creación de un proyecto.

Puerto de `_verificar_unicos` y `_buscar_duplicado_por_nombre` de
`app/api/v1/proyectos.py`. Viven acá porque las usan DOS caminos —`POST
/proyectos` y `POST /comercial/oportunidades/{id}/proyectos`— y reimplementarlas
en uno es como los dos dejan de coincidir.

**Las dos son distintas y no intercambiables.** `verificar_unicos` es una
restricción dura de la base y devuelve 409 sin salida; `buscar_duplicado_por_nombre`
es un AVISO permisivo que la persona puede saltarse con `forzar=true`.
"""

from __future__ import annotations

from api.exceptions import Conflict
from apps.comun.nombre_matching import mejor_candidato
from apps.proyectos.models import Proyecto

# Columnas con UNIQUE en la base, con el nombre que el usuario reconoce.
UNIQUE_COLS = {
    "sub_project": "API ID Unergy",
    "project_id_solenium": "ID de Solenium (generación)",
    "sunfactory_project_id": "ID de Sun Factory",
}


def verificar_unicos(payload: dict, excluir_id: int | None = None) -> None:
    """Chequeo PROACTIVO de las columnas UNIQUE.

    Da un mensaje que nombra el proyecto en conflicto, en vez del IntegrityError
    opaco que devolvería la base.
    """
    for columna, etiqueta in UNIQUE_COLS.items():
        nuevo = payload.get(columna)
        if nuevo in (None, ""):
            continue
        qs = Proyecto.objects.filter(**{columna: nuevo})
        if excluir_id is not None:
            qs = qs.exclude(pk=excluir_id)
        conflicto = qs.first()
        if conflicto:
            raise Conflict(
                f"El {etiqueta} '{nuevo}' ya está asignado al proyecto "
                f"'{conflicto.nombre_comercial}' (ID {conflicto.id}). "
                f"Cada {etiqueta} debe ser único."
            )


def buscar_duplicado_por_nombre(nombre_comercial: str | None,
                                tipo_proyecto: str | None = None) -> Proyecto | None:
    """Un proyecto existente con nombre parecido, por solapamiento de tokens +
    similitud de texto (el mismo algoritmo que reconcilia Quoia/Solenium/GESCON).

    Detecta parecidos aunque no sea un caso de "un nombre contenido en el otro"
    —"AGGE Extractora Monterrey" contra "AGGE Frontera Monterrey"—. Con
    `tipo_proyecto` solo compara contra proyectos del mismo tipo, lo que reduce
    los falsos positivos entre proyectos de naturaleza distinta que comparten
    palabras.

    Es deliberadamente PERMISIVO: puede marcar como parecidas dos fases reales
    de un mismo desarrollo ("Chinú Sur" y "Chinú Sur 2"). Es aceptable porque el
    aviso no bloquea — la persona confirma "crear de todos modos" con un clic.
    """
    if not nombre_comercial:
        return None
    qs = Proyecto.objects.filter(deleted_at__isnull=True)
    if tipo_proyecto:
        qs = qs.filter(tipo_proyecto=tipo_proyecto)
    item, _score = mejor_candidato(nombre_comercial, [(c, [c.nombre_comercial]) for c in qs])
    return item
