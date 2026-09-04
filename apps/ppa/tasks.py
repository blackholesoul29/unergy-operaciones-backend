"""Tareas programadas del dominio `ppa`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="ppa.alertas_vencimiento")
def alertas_vencimiento() -> str:
    """Alertas proactivas de vencimiento de contratos PPA (90/60/30 días).

    A las 8:15 y no a las 8:00 para no competir por la misma franja exacta con
    las alertas de representación, que salen por el mismo SMTP.
    """
    from apps.ppa.services.vencimientos import revisar_vencimientos

    creadas = revisar_vencimientos()
    if creadas:
        logger.info("alertas de vencimiento de PPA creadas: %d", len(creadas))
    return f"{len(creadas)} alertas nuevas"
