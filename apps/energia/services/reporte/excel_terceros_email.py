"""Lectura automática del Excel de Cedillanos vía correo (IMAP) --
Cedillanos maneja su propio CGM y envía un Excel diario a
operaciones@unergy.io en vez de que alguien lo suba a mano. Ver
excel_terceros.py para el formato del archivo; aplicar_excel_terceros() ahí
es el procesamiento compartido con el upload manual (POST
/cargar-excel-terceros).

El nombre/código del asunto del correo (ej. "FRT85329 - Alsec Llanos", ver
captura 2026-08-13) es del sistema del remitente (cgm@erco.energy) -- no
tiene relación con nuestro frt_code. El frontera_id de destino es fijo acá,
no lo decide el contenido del correo ni del Excel (mismo criterio que
aplicar_excel_terceros(): "qué frontera_id recibe los datos lo decide la
URL/config, no el contenido del archivo").
"""
from __future__ import annotations

import email
import imaplib
import logging

from apps.comun.config import settings
from apps.energia.services.reporte.excel_terceros import aplicar_excel_terceros

from django.db import close_old_connections, transaction


class _SinFilas(Exception):
    """El adjunto se leyó pero no traía ninguna fila 'Primary' válida.

    Se usa para revertir la transacción del adjunto sin confundirse con un
    ValueError de formato, que significa otra cosa.
    """


logger = logging.getLogger("reporte_energia.excel_terceros_email")

CEDILLANOS_FRONTERA_ID = 79  # Cedillanos_excedentes, Frt88292
# Dominio, no una casilla puntual -- el correo diario le llega a este mismo
# hilo, pero no siempre lo manda "cgm@erco.energy": el 2026-08-27 lo mandó
# Johan Felipe González (jgonzaleso@erco.energy), otra persona del mismo
# hilo/organización, y el filtro exacto por remitente hizo que las 9
# corridas entre 4-6am no encontraran el correo (llegó a las 4:41am, dentro
# de la ventana) -- sin ningún error en el log, porque "sin correos nuevos"
# es una corrida válida, no una falla. Filtrar por dominio es robusto a
# cualquier persona de Cedillanos que responda o envíe desde ese hilo.
CEDILLANOS_DOMINIO_REMITENTE = "erco.energy"
# El SEARCH de Gmail busca por TOKEN completo, no por subcadena (probado en
# vivo 2026-08-14): "85329" nunca hace match con "FRT85329" en el asunto,
# aunque sí sea una subcadena real -- hay que usar el token completo tal
# como aparece en el asunto ("RE: FRT85329 - Alsec Llanos").
CEDILLANOS_ASUNTO_CLAVE = "FRT85329"


def _extraer_adjuntos_excel(msg: email.message.Message) -> list[tuple[str, bytes]]:
    """(nombre_archivo, contenido) de cada adjunto .xlsx/.xls del correo."""
    adjuntos: list[tuple[str, bytes]] = []
    for parte in msg.walk():
        nombre = parte.get_filename()
        if not nombre or not nombre.lower().endswith((".xlsx", ".xls")):
            continue
        contenido = parte.get_payload(decode=True)
        if contenido:
            adjuntos.append((nombre, contenido))
    return adjuntos


def revisar_correo_cedillanos() -> None:
    """Busca en operaciones@unergy.io correos SIN LEER de Cedillanos (ver
    CEDILLANOS_DOMINIO_REMITENTE/CEDILLANOS_ASUNTO_CLAVE), aplica el primer adjunto
    Excel que cargue con éxito a CEDILLANOS_FRONTERA_ID, y marca el correo
    como leído solo si algo se cargó -- si falla (adjunto con formato
    inesperado, sin filas 'Primary', etc.) queda sin leer para reintentar
    en la próxima corrida, en vez de perderse en silencio.

    Pensado para correr una vez al día (ver main.py). No lanza excepción
    hacia el llamador -- cualquier falla de conexión/autenticación queda
    solo en el log, para no tumbar el resto del scheduler.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info("IMAP: SMTP_USER/SMTP_PASSWORD no configurados, se omite la revisión de correo")
        return

    try:
        imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        imap.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    except Exception as exc:
        logger.error("IMAP: no se pudo conectar/autenticar contra %s: %s", settings.IMAP_HOST, exc)
        return

    try:
        imap.select("INBOX")
        criterio = f'(UNSEEN FROM "{CEDILLANOS_DOMINIO_REMITENTE}" SUBJECT "{CEDILLANOS_ASUNTO_CLAVE}")'
        status, data = imap.search(None, criterio)
        if status != "OK":
            logger.error("IMAP: búsqueda falló: %s", data)
            return

        ids = data[0].split() if data and data[0] else []
        if not ids:
            logger.info("IMAP: sin correos nuevos de Cedillanos")
            return

        try:
            for msg_id in ids:
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                adjuntos = _extraer_adjuntos_excel(msg)
                if not adjuntos:
                    logger.warning("IMAP: correo de Cedillanos sin adjunto Excel -- asunto=%r", msg.get("Subject"))
                    continue

                cargado = False
                if len(adjuntos) > 1:
                    # No debería pasar (Cedillanos manda un Excel diario, un
                    # solo adjunto por correo) -- si llega a pasar, antes se
                    # aplicaban TODOS en el orden de msg.walk(), y el último
                    # que cargara bien pisaba en silencio lo que ya había
                    # cargado uno anterior para las mismas fechas. Se avisa
                    # para que quede a la vista (auditoría Reporte ASIC
                    # 2026-08-26).
                    logger.warning(
                        "IMAP: correo de Cedillanos con %d adjuntos Excel -- se aplica solo el "
                        "primero que cargue con éxito, el resto se ignora. asunto=%r",
                        len(adjuntos), msg.get("Subject"),
                    )
                for nombre, contenido in adjuntos:
                    try:
                        # Cada adjunto es todo o nada: si el Excel viene mal a
                        # media carga, no queda medio día escrito.
                        with transaction.atomic():
                            fechas = aplicar_excel_terceros(
                                CEDILLANOS_FRONTERA_ID, contenido)
                            if not fechas:
                                raise _SinFilas(nombre)
                    except ValueError as e:
                        logger.error("IMAP: %s con formato inesperado: %s", nombre, e)
                        continue
                    except _SinFilas:
                        logger.warning("IMAP: %s sin filas 'Primary' válidas", nombre)
                        continue
                    logger.info("IMAP: cargado %s -- fechas %s", nombre, sorted(fechas))
                    cargado = True
                    break  # solo el primero que cargue con éxito -- ver docstring de esta función

                if cargado:
                    imap.store(msg_id, "+FLAGS", "\\Seen")
        finally:
            close_old_connections()
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()
