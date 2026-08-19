"""Diagnóstico de la conexión IMAP de mandatos. Solo lee y reporta al log.

Provisional. Existe para validar en producción que el App Password funciona y
que la carpeta de Enviados se detecta, ANTES de prender cualquier escritura --
si la autenticación va a fallar, es mucho mejor descubrirlo con el sistema en
modo lectura que con un cron escribiendo en una tabla con datos reales.

Lo reemplaza la Tarea 5 del Plan 2, que apunta el cron a la ingesta de verdad.
Cuando eso pase, este módulo se puede borrar.
"""
from __future__ import annotations

import imaplib
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger("mandatos.diagnostico")

REMITENTES = ("vlondono@jbp.com.co", "jessica@unergy.io")
DIAS = 30


def _contar(imap: imaplib.IMAP4_SSL, carpeta: str, campo: str, direccion: str) -> int | None:
    """Cuántos correos hay. None si la búsqueda falla."""
    try:
        imap.select(carpeta, readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=DIAS)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{desde}" {campo} "{direccion}")')
        if status != "OK":
            return None
        return len(data[0].split()) if data and data[0] else 0
    except Exception as exc:
        logger.warning("Diagnóstico: fallo buscando %s en %r: %s", direccion, carpeta, exc)
        return None


def diagnostico_imap() -> None:
    """Conecta, cuenta lo que encontraría, y lo escribe en el log. No toca la BD.

    Nunca lanza: es un diagnóstico, no puede tumbar el scheduler.
    """
    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("Diagnóstico IMAP: credenciales no configuradas, se omite")
        return

    try:
        imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        imap.login(settings.MANDATOS_IMAP_USER, settings.MANDATOS_IMAP_PASSWORD)
    except Exception as exc:
        logger.error("Diagnóstico IMAP: AUTENTICACIÓN FALLÓ contra %s como %s: %s",
                     settings.IMAP_HOST, settings.MANDATOS_IMAP_USER, exc)
        return

    logger.info("Diagnóstico IMAP: autenticado OK como %s", settings.MANDATOS_IMAP_USER)
    try:
        from app.services.mandatos.imap_client import carpeta_enviados

        enviados = carpeta_enviados(imap)
        logger.info("Diagnóstico IMAP: carpeta de Enviados = %r", enviados)

        for direccion in REMITENTES:
            n = _contar(imap, "INBOX", "FROM", direccion)
            logger.info("Diagnóstico IMAP: INBOX FROM %s -> %s correos en %d días",
                        direccion, n, DIAS)

        if enviados:
            n = _contar(imap, enviados, "TO", REMITENTES[0])
            logger.info("Diagnóstico IMAP: %r TO %s -> %s correos en %d días",
                        enviados, REMITENTES[0], n, DIAS)
        else:
            logger.warning("Diagnóstico IMAP: sin carpeta de Enviados, la "
                           "reconciliación por conteo no podrá funcionar")
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass
