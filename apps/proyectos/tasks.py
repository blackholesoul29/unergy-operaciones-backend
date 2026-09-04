"""Tareas programadas del dominio `proyectos`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="proyectos.recalcular_gen_promedio")
def recalcular_gen_promedio() -> str:
    """Recalcula `gen_mensual_promedio_mwh` (ventana móvil de 30 días).

    Antes solo se recalculaba por llamada manual al endpoint, sin scheduler ni
    botón en el frontend que lo disparara: quedaba desactualizado en silencio
    —17 días sin tocar, confirmado el 2026-08-27— mientras las vistas de
    contrato lo seguían tratando como dato confiable.

    `force=False` respeta los valores cargados a mano, mismo criterio que el
    backfill de comercialización, con quien comparte franja horaria. Va 10 min
    antes que ese: ambos leen la misma API de generación de Unergy y separarlos
    evita que compitan por el rate limit en el mismo segundo.
    """
    from apps.proyectos.services import gen_promedio

    res = gen_promedio.recalcular(dry_run=False, force=False)
    if "error" in res:
        logger.error("recálculo de generación promedio falló: %s", res["error"])
        return f"error: {res['error']}"
    resumen = (f"{res['n_actualizados']} actualizados, {res['n_sin_datos']} sin datos, "
               f"{res['n_saltados']} saltados, {res['n_fallidos']} fallidos")
    logger.info("recálculo de generación promedio: %s", resumen)
    return resumen
