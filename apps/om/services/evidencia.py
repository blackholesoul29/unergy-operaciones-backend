"""Las seis secciones de evidencia del informe de puesta en marcha.

Cada sección apunta a un sitio DISTINTO dentro de los JSONB de la ficha: unas a
un campo suelto, otras a un subcampo anidado. En vez de un `if/elif` por
sección, cada una declara cómo leer y cómo escribir su lista, y los endpoints de
subir y borrar trabajan contra ese par sin saber dónde vive nada.

Agregar una sección nueva = una entrada en `SECCIONES`.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Seccion:
    leer: Callable
    escribir: Callable
    etiqueta: str


def _seccion_de_campo(campo: str, etiqueta: str) -> Seccion:
    """Evidencia guardada directamente en un campo de la ficha."""
    return Seccion(
        leer=lambda ficha: getattr(ficha, campo) or [],
        escribir=lambda ficha, lista: setattr(ficha, campo, lista),
        etiqueta=etiqueta,
    )


def _seccion_en_jsonb(campo: str, etiqueta: str) -> Seccion:
    """Evidencia bajo la clave `evidencia` de un JSONB."""
    def escribir(ficha, lista):
        setattr(ficha, campo, {**(getattr(ficha, campo) or {}), "evidencia": lista})

    return Seccion(
        leer=lambda ficha: (getattr(ficha, campo) or {}).get("evidencia") or [],
        escribir=escribir,
        etiqueta=etiqueta,
    )


def _seccion_anidada(campo: str, clave: str, etiqueta: str) -> Seccion:
    """Evidencia dos niveles adentro: `campo[clave]["evidencia"]`."""
    def escribir(ficha, lista):
        contenido = dict(getattr(ficha, campo) or {})
        contenido[clave] = {**(contenido.get(clave) or {}), "evidencia": lista}
        setattr(ficha, campo, contenido)

    return Seccion(
        leer=lambda ficha: (
            ((getattr(ficha, campo) or {}).get(clave) or {}).get("evidencia") or []
        ),
        escribir=escribir,
        etiqueta=etiqueta,
    )


# `arquitectura` es la única que existía antes de la fusión con
# `proyecto_inicio_operacion` (2026-08-31); las otras cinco son los cuatro
# checklist de comisionamiento — frontera aporta dos, principal y respaldo.
SECCIONES: dict[str, Seccion] = {
    "arquitectura": _seccion_de_campo(
        "evidencia_arquitectura", "Arquitectura de comunicación"
    ),
    "checklist-fusion-solar": _seccion_en_jsonb(
        "checklist_fusion_solar", "Fusion Solar"
    ),
    "checklist-frontera-principal": _seccion_anidada(
        "checklist_frontera", "principal", "Frontera — Medidor principal"
    ),
    "checklist-frontera-respaldo": _seccion_anidada(
        "checklist_frontera", "respaldo", "Frontera — Medidor de respaldo"
    ),
    "checklist-estacion-meteo": _seccion_anidada(
        "checklist_estacion_meteo", "reporta_datos", "Estación meteorológica"
    ),
    "checklist-reconectador": _seccion_en_jsonb(
        "checklist_reconectador", "Reconectador"
    ),
}


def relacionada(ficha) -> list[dict]:
    """Toda la evidencia ya subida, aplanada, para mostrarla y enlazarla al PDF.

    No sube nada nuevo: es la MISMA evidencia de los checklist, recogida en una
    sola lista para que el informe no obligue a volver a adjuntarla.
    """
    if ficha is None:
        return []
    items = []
    # Starlink cuelga de Fusion Solar y no tiene sección propia, pero su
    # evidencia sí debe aparecer en el informe.
    fuentes = [(
        "Starlink",
        ((ficha.checklist_fusion_solar or {}).get("starlink") or {}).get("evidencia"),
    )]
    fuentes += [
        (seccion.etiqueta, seccion.leer(ficha)) for seccion in SECCIONES.values()
    ]
    for etiqueta, lista in fuentes:
        for evidencia in (lista or []):
            if evidencia.get("url"):
                items.append({
                    "seccion": etiqueta,
                    "nombre": evidencia.get("nombre") or "Archivo",
                    "url": evidencia["url"],
                })
    return items
