"""Sincroniza `operador_red_id` entre un proyecto y sus fronteras.

El vínculo existía solo en `fronteras` —y sin forma de editarlo desde la API—
mientras `proyectos.operador_red` era texto libre sin relación con el catálogo.
Por eso un proyecto podía mostrar «Afinia» en su ficha y salir como «sin
operador» en Reporte CGM a la vez (caso real del 2026-07-10, «MGS 0032 - El Paso
Norte»).

**Nunca se pisa un valor ya diligenciado: solo se rellenan huecos.**
"""

from apps.fronteras import models as fr_models


def sincronizar(proyecto) -> None:
    """Rellena en las DOS direcciones, en la misma pasada.

    Primero el proyecto adopta el operador de la primera frontera VIVA que lo
    tenga —si el proyecto aún no tiene ninguno— y después se propaga al resto
    de fronteras vivas que sigan sin él. Así una sola frontera con el dato lo
    pasa a sus hermanas en la misma llamada, no solo al proyecto.

    Una frontera borrada ni presta ni recibe el dato: ya no cuenta.
    """
    vivas = list(
        fr_models.Frontera.objects.filter(
            proyecto=proyecto, deleted_at__isnull=True
        )
    )

    if proyecto.operador_red_id is None:
        prestado = next(
            (f.operador_red_id for f in vivas if f.operador_red_id is not None),
            None,
        )
        if prestado is not None:
            proyecto.operador_red_id = prestado
            proyecto.save(update_fields=["operador_red"])

    if proyecto.operador_red_id is None:
        return

    sin_operador = [f for f in vivas if f.operador_red_id is None]
    for frontera in sin_operador:
        frontera.operador_red_id = proyecto.operador_red_id
    if sin_operador:
        fr_models.Frontera.objects.bulk_update(sin_operador, ["operador_red"])
