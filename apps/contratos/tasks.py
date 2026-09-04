"""Tareas programadas del dominio `contratos`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="contratos.alertas_representacion")
def alertas_representacion() -> str:
    """Avisa 30 y 15 días antes del aniversario de un contrato CGM/Representación,
    con la tarifa ya indexada por IPC."""
    from apps.contratos.services.alertas_representacion import revisar_aniversarios

    enviadas = revisar_aniversarios()
    return f"{enviadas} alertas enviadas"
