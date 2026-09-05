"""Sincroniza `operador_red_id` entre un proyecto y sus fronteras.

Puerto de `app/services/operadores_red_sync.py`.

Antes el vínculo existía solo en `fronteras` —y sin forma de editarlo desde la
API— mientras `proyectos.operador_red` era texto libre sin relación con el
catálogo: por eso un proyecto podía mostrar "Afinia" en su ficha y aparecer como
"sin operador" en Reporte CGM al mismo tiempo (caso real 2026-07-10, "MGS 0032 -
El Paso Norte").

**Nunca se pisa un valor ya diligenciado, solo se rellenan huecos** — mismo
principio que el resto de las sincronizaciones.
"""

from __future__ import annotations

from apps.fronteras.models import Frontera
from apps.proyectos.models import Proyecto


def sincronizar_operador_red(proyecto: Proyecto) -> None:
    """Rellena `operador_red_id` en las DOS direcciones, en la misma pasada.

    Primero el proyecto adopta el de la primera frontera VIVA que lo tenga (si
    todavía no tiene ninguno), y después siempre cascadea hacia el resto de
    fronteras vivas que sigan sin él — así una sola frontera con el dato
    diligenciado lo propaga a sus hermanas en la misma llamada, no solo al
    proyecto.

    Una frontera borrada ni presta ni recibe el dato: ya no cuenta.
    """
    vivas = list(Frontera.objects.filter(proyecto_id=proyecto.id, deleted_at__isnull=True))

    if proyecto.operador_red_id is None:
        for f in vivas:
            if f.operador_red_id is not None:
                proyecto.operador_red_id = f.operador_red_id
                proyecto.save(update_fields=["operador_red_id"])
                break

    if proyecto.operador_red_id is not None:
        sin_operador = [f.id for f in vivas if f.operador_red_id is None]
        if sin_operador:
            Frontera.objects.filter(id__in=sin_operador).update(
                operador_red_id=proyecto.operador_red_id
            )
