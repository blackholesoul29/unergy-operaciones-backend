"""Sincroniza `operador_red_id` entre un proyecto y sus fronteras.

Antes existía el vínculo solo en `fronteras` (y sin ninguna forma de editarlo
desde la API) mientras `proyectos.operador_red` era texto libre sin relación
con el catálogo -- por eso un proyecto podía mostrar "Afinia" en su ficha y
aparecer como "sin operador" en Reporte CGM al mismo tiempo (caso real
2026-07-10, "MGS 0032 - EL Paso Norte").

Regla: nunca se pisa un valor ya diligenciado, solo se rellenan huecos --
mismo principio que `backfill_ubicacion` y el resto de sincronizaciones de
esta sesión."""
from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto


def sincronizar_operador_red(db: Session, proyecto: Proyecto) -> None:
    """Rellena `operador_red_id` en las dos direcciones, en la misma pasada:
    primero adopta el del proyecto desde la primera frontera VIVA que lo
    tenga (si el proyecto todavía no tiene ninguno), y siempre cascada hacia
    el resto de fronteras VIVAS que sigan sin él -- así una sola frontera con
    el dato ya diligenciado lo propaga a sus hermanas en la misma llamada, no
    solo al proyecto. Una frontera borrada ni presta ni recibe el dato: ya no
    cuenta para esta sincronización. No hace commit -- el caller ya está
    dentro de una transacción."""
    fronteras_vivas = [f for f in proyecto.fronteras if f.deleted_at is None]
    if proyecto.operador_red_id is None:
        for f in fronteras_vivas:
            if f.operador_red_id is not None:
                proyecto.operador_red_id = f.operador_red_id
                break
    if proyecto.operador_red_id is not None:
        for f in fronteras_vivas:
            if f.operador_red_id is None:
                f.operador_red_id = proyecto.operador_red_id
