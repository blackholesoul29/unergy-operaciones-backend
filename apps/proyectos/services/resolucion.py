"""Resolver una planta por nombre, sin ambigüedad silenciosa.

Puerto de `_id_por_nombre` de `app/api/v1/proyectos.py`. Vive acá y no en la
vista porque lo consumen varios recursos —`/proyectos/buscar` y
`/fallas/por-proyecto` hoy— y cada copia propia es una forma nueva de resolver
mal el mismo nombre.

**El match es exacto sobre el nombre normalizado**: tolera mayúsculas, tildes,
guiones y espacios de más, pero NO es difuso. Es deliberado: quien consume esto
es un script o una persona encadenando llamadas, y devolverle el proyecto
equivocado en silencio es peor que devolverle un error. El matcher permisivo
(`mejor_candidato`) existe y se usa para avisar de duplicados al crear; acá no.

`nombre_comercial` no tiene UNIQUE y en producción hay duplicados reales — de ahí
el 409 con la lista de candidatos, para que quien llama elija un id.
"""

from __future__ import annotations

from api.exceptions import Conflict, NoProcesable
from apps.comun.nombre_matching import normalizar
from apps.proyectos.models import Proyecto
from rest_framework.exceptions import NotFound


def clave_nombre(texto: str | None) -> str:
    """Forma comparable de un nombre: sin tildes, en minúsculas, sin caracteres
    no alfanuméricos y con los espacios colapsados.

    Reusa `normalizar` (la misma cadena que reconcilia nombres contra
    Quoia/Solenium/GESCON), que convierte los caracteres raros en espacios pero
    no colapsa los internos — de ahí el split/join.
    """
    return " ".join(normalizar(texto or "").split())


def id_por_nombre(nombre: str) -> int:
    """El id de UN proyecto, o un error accionable.

    Devuelve solo el id —no la fila cargada— para que cada quien traiga lo que
    necesita: `/proyectos/buscar` quiere el detalle con sus precargas, pero
    `/fallas/por-proyecto` solo necesita identificar la planta.
    """
    clave = clave_nombre(nombre)
    if not clave:
        raise NoProcesable("El parámetro 'nombre' no puede estar vacío.")

    filas = Proyecto.objects.filter(deleted_at__isnull=True).values("id", "nombre_comercial")
    coincidencias = [f for f in filas if clave_nombre(f["nombre_comercial"]) == clave]

    if not coincidencias:
        raise NotFound(
            f"No existe un proyecto cuyo nombre coincida con '{nombre}'. "
            f"Consultá GET /api/v1/proyectos/lista para ver los nombres disponibles."
        )
    if len(coincidencias) > 1:
        raise Conflict({
            "mensaje": (
                f"Hay {len(coincidencias)} proyectos cuyo nombre coincide con "
                f"'{nombre}'. Consultá el detalle por ID."
            ),
            "nombre_ambiguo": True,
            "candidatos": [
                {"id": f["id"], "nombre_comercial": f["nombre_comercial"]}
                for f in coincidencias
            ],
        })
    return coincidencias[0]["id"]


def resolver_proyecto(proyecto_id=None, api_id_unergy=None, nombre=None) -> Proyecto:
    """La planta por id interno, llave de la API de Unergy o nombre exacto.

    Exige EXACTAMENTE una llave. Una versión propia con prefiltro `ILIKE` sobre
    el texto crudo es sensible a tildes: "Santa Fe 2" no traía a "Santa Fé 2"
    como candidata, así que un nombre ambiguo se resolvía como único y la
    integración se llevaba las fallas de la planta equivocada sin enterarse —
    justo el caso que el 409 existe para atrapar.
    """
    llaves = [k for k in (proyecto_id, api_id_unergy, nombre) if k not in (None, "")]
    if len(llaves) != 1:
        raise NoProcesable("Indique exactamente una de: proyecto_id, api_id_unergy, nombre.")

    vivos = Proyecto.objects.filter(deleted_at__isnull=True)
    if proyecto_id is not None:
        proyecto = vivos.filter(pk=proyecto_id).first()
        if not proyecto:
            raise NotFound(f"No existe un proyecto con id {proyecto_id}.")
        return proyecto

    if api_id_unergy:
        proyecto = vivos.filter(sub_project=api_id_unergy).first()
        if not proyecto:
            raise NotFound(f"No existe un proyecto con api_id_unergy '{api_id_unergy}'.")
        return proyecto

    return vivos.get(pk=id_por_nombre(nombre))
