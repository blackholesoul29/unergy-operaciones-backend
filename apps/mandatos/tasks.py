"""Tareas programadas del dominio `mandatos`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="mandatos.revisar_correos")
def revisar_correos() -> dict:
    """Lee el buzón de mandatos y alimenta `finanzas_mandatos`.

    Cada hora de 7am a 7pm: los correos de la revisoría y los envíos a
    inversionistas llegan en horario laboral. Sin correos nuevos la corrida es
    solo un IMAP SEARCH que no toca la base.

    Tres pasadas por buzón — lo que llega de la revisoría, lo que se manda a los
    inversionistas, y lo que sale hacia la revisoría (carpeta Enviados, la que
    permite saber cuántos mandatos se enviaron). Transacción por correo, y la
    deduplicación va por Message-ID, así que una corrida interrumpida retoma
    donde quedó.

    El buzón es de una persona y nunca se modifica: todo `select` va con
    `readonly=True` y no se marca nada como leído.
    """
    from apps.mandatos.services.correo_sync import ingesta_en_curso, revisar_correos as revisar

    if ingesta_en_curso():
        # Una corrida manual desde la pantalla puede estar andando. Dos a la vez
        # podrían tomar el mismo correo y duplicar la subida a Drive, que es lo
        # único acá que no se deshace solo.
        logger.info("ya hay una corrida en curso — se omite esta franja")
        return {"omitida": "corrida en curso"}
    return revisar()
