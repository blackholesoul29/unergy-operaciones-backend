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


# Nombres de respaldo, por si el servidor no publica la bandera \Sent. El orden
# importa: primero los de Gmail, que es lo que usamos.
_ENVIADOS_CONOCIDOS = (
    "[Gmail]/Enviados",
    "[Gmail]/Sent Mail",
    "[Google Mail]/Enviados",
    "Enviados",
    "Sent",
)


def carpeta_enviados(imap: imaplib.IMAP4_SSL) -> str | None:
    """Nombre de la carpeta de Enviados, o None si no se puede determinar.

    Se busca por la bandera `\\Sent` del RFC 6154, no por nombre: el nombre
    depende del idioma de la cuenta ("Enviados" vs "Sent Mail") y cambiaría si
    alguien toca la configuración de Gmail. La bandera no.

    Si el servidor no publica la bandera, se cae a una lista de nombres
    conocidos. Si tampoco, se devuelve None y el llamador decide -- preferimos
    no leer nada a leer la carpeta equivocada.
    """
    try:
        status, lineas = imap.list()
    except Exception as exc:
        logger.error("IMAP mandatos: no se pudo listar carpetas: %s", exc)
        return None
    if status != "OK" or not lineas:
        return None

    disponibles: list[str] = []
    for linea in lineas:
        texto = linea.decode("utf-8", errors="replace") if isinstance(linea, bytes) else str(linea)
        # Formato: (\HasNoChildren \Sent) "/" "[Gmail]/Enviados"
        nombre = texto.split(' "/" ')[-1].strip().strip('"')
        disponibles.append(nombre)
        if "\\Sent" in texto:
            return nombre

    for candidato in _ENVIADOS_CONOCIDOS:
        if candidato in disponibles:
            logger.info("IMAP mandatos: sin bandera \\Sent, usando %r", candidato)
            return candidato

    logger.error("IMAP mandatos: no se encontró la carpeta de Enviados. Disponibles: %s",
                 disponibles)
    return None


def buscar_correos(direccion: str, dias: int = 30, *,
                   carpeta: str = "INBOX", campo: str = "FROM") -> list[CorreoCrudo]:
    """Correos de/para `direccion` en los últimos `dias`, dentro de `carpeta`.

    `campo` es "FROM" para lo que llega y "TO" para lo que sale. Los salientes
    viven en la carpeta de Enviados, no en INBOX -- ver carpeta_enviados().

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
        imap.select(carpeta, readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{desde}" {campo} "{direccion}")')
        if status != "OK":
            logger.error("IMAP mandatos: búsqueda falló para %s: %s", direccion, data)
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
                remitente=_decodifica(msg.get("From")) or direccion,
                asunto=_decodifica(msg.get("Subject")),
                cuerpo=_cuerpo_de(msg),
                adjuntos=_adjuntos_de(msg),
            ))
    except Exception as exc:
        logger.error("IMAP mandatos: fallo leyendo correos de %s: %s", direccion, exc)
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
