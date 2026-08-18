"""Acceso IMAP de solo lectura al buzón de mandatos.

Solo I/O -- no sabe qué es un mandato. Nunca marca correos como leídos ni
modifica etiquetas: adhara@unergy.io es el buzón de una persona y la plataforma
no debe alterar su bandeja (a diferencia de excel_terceros_email.py, que lee
una cuenta operativa y sí marca \\Seen).

Como no se usa UNSEEN, la deduplicación va por Message-ID contra la tabla
mandato_correos -- ver email_sync.py.
"""
from __future__ import annotations

import email
import imaplib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from app.core.config import settings

logger = logging.getLogger("mandatos.imap")


@dataclass
class CorreoCrudo:
    message_id: str
    fecha: datetime
    remitente: str
    asunto: str
    cuerpo: str                                    # texto plano ya resuelto
    adjuntos: list[tuple[str, bytes]] = field(default_factory=list)


def _decodifica(valor: str | None) -> str:
    """Cabecera RFC2047 ('=?UTF-8?B?...?=') → str legible."""
    if not valor:
        return ""
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return valor


def _cuerpo_de(msg: email.message.Message) -> str:
    """Texto del correo. Prefiere text/plain; si no hay, convierte el HTML."""
    from app.services.mandatos.email_parser import html_a_texto

    plano, html = "", ""
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart" or parte.get_filename():
            continue
        try:
            crudo = parte.get_payload(decode=True) or b""
            texto = crudo.decode(parte.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if parte.get_content_type() == "text/plain" and not plano:
            plano = texto
        elif parte.get_content_type() == "text/html" and not html:
            html = texto
    return plano.strip() or html_a_texto(html)


def _adjuntos_de(msg: email.message.Message) -> list[tuple[str, bytes]]:
    salida: list[tuple[str, bytes]] = []
    for parte in msg.walk():
        nombre = _decodifica(parte.get_filename())
        if not nombre:
            continue
        contenido = parte.get_payload(decode=True)
        if contenido:
            salida.append((nombre, contenido))
    return salida


def buscar_correos(remitente: str, dias: int = 30) -> list[CorreoCrudo]:
    """Correos de `remitente` recibidos en los últimos `dias`.

    Devuelve [] ante cualquier fallo de conexión, autenticación o búsqueda --
    nunca lanza hacia el llamador, para no tumbar el scheduler.
    """
    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("IMAP mandatos: credenciales no configuradas, se omite la revisión")
        return []

    try:
        imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        imap.login(settings.MANDATOS_IMAP_USER, settings.MANDATOS_IMAP_PASSWORD)
    except Exception as exc:
        logger.error("IMAP mandatos: no se pudo conectar/autenticar contra %s: %s",
                     settings.IMAP_HOST, exc)
        return []

    correos: list[CorreoCrudo] = []
    try:
        imap.select("INBOX", readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{desde}" FROM "{remitente}")')
        if status != "OK":
            logger.error("IMAP mandatos: búsqueda falló para %s: %s", remitente, data)
            return []

        for uid in (data[0].split() if data and data[0] else []):
            status, msg_data = imap.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            message_id = (msg.get("Message-ID") or "").strip()
            if not message_id:
                logger.warning("IMAP mandatos: correo sin Message-ID, se omite -- asunto=%r",
                               msg.get("Subject"))
                continue
            try:
                fecha = parsedate_to_datetime(msg.get("Date"))
            except Exception:
                fecha = datetime.now(timezone.utc)
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            correos.append(CorreoCrudo(
                message_id=message_id,
                fecha=fecha,
                remitente=remitente,
                asunto=_decodifica(msg.get("Subject")),
                cuerpo=_cuerpo_de(msg),
                adjuntos=_adjuntos_de(msg),
            ))
    except Exception as exc:
        logger.error("IMAP mandatos: fallo leyendo correos de %s: %s", remitente, exc)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass
    return correos
