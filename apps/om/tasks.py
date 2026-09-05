"""Tareas programadas del dominio `om`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="om.revisar_ipc_del_anio")
def revisar_ipc_del_anio() -> str:
    """Cada 1 de enero: si falta la tasa de IPC del año, deja el registro abierto.

    No inventa el número —el DANE lo publica a principios de enero y nadie puede
    saberlo el día 1— sino que crea la fila en 0,0 con `confirmado=False` y
    `fuente='pendiente_confirmacion'`, para que el año aparezca en la pantalla
    esperando el dato en vez de faltar en silencio. Quien lo confirme escribe la
    tasa real.

    Idempotente: si la fila ya existe no la toca, ni siquiera para pisar una
    confirmada.
    """
    from apps.om.models import OmIpcTasa
    from apps.plataforma.services.fechas import hoy_col

    anio = hoy_col().year
    _, creada = OmIpcTasa.objects.get_or_create(
        año=anio,
        defaults={"tasa": 0.0, "confirmado": False,
                  "fuente": "pendiente_confirmacion"},
    )
    if creada:
        logger.info("tasa de IPC %d creada pendiente de confirmación", anio)
        return f"IPC {anio} pendiente de confirmación creada"
    return f"IPC {anio} ya existía"
