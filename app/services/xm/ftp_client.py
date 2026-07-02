"""Cliente FTPS real contra el servidor de XM.

Contexto SSL relajado (check_hostname/verify_mode desactivados) porque
el servidor de XM no pasa verificación TLS estricta — patrón tomado de
aenc_reporte.py, que ya corre en producción contra este mismo servidor.
"""
import ftplib
import io
import logging
import ssl

from app.services.xm.exceptions import (
    FTPAuthenticationError, FTPConnectionError, FTPFileNotFoundError,
    FTPPermissionError, FTPTimeoutError,
)

logger = logging.getLogger(__name__)


def conectar_ftp(host: str, usuario: str, clave: str, directorio: str,
                  puerto: int = 210, timeout: int = 30) -> ftplib.FTP_TLS:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    logger.info("Conectando a %s:%s -> %s", host, puerto, directorio)
    ftp = ftplib.FTP_TLS(context=ctx)
    try:
        ftp.connect(host, puerto, timeout=timeout)
    except TimeoutError as e:
        logger.warning("Timeout conectando a %s:%s: %s", host, puerto, e)
        raise FTPTimeoutError(f"Conexión a {host}:{puerto} agotó el tiempo de espera: {e}")
    except OSError as e:
        logger.warning("No se pudo conectar a %s:%s: %s", host, puerto, e)
        raise FTPConnectionError(f"No se pudo conectar a {host}:{puerto}: {e}")

    try:
        ftp.auth()
        ftp.login(user=usuario, passwd=clave)
        ftp.prot_p()
    except ftplib.error_perm as e:
        logger.warning("Autenticación fallida para '%s': %s", usuario, e)
        raise FTPAuthenticationError(f"Autenticación FTP fallida para '{usuario}': {e}")

    try:
        ftp.cwd(directorio)
    except ftplib.error_perm as e:
        if "550" in str(e):
            logger.warning("Directorio no encontrado: %s", directorio)
            raise FTPFileNotFoundError(f"Directorio no encontrado: {directorio}: {e}")
        logger.warning("Sin acceso a %s: %s", directorio, e)
        raise FTPPermissionError(f"Sin acceso a {directorio}: {e}")

    logger.info("Conectado a %s -> %s", host, directorio)
    return ftp


def listar_directorio(ftp: ftplib.FTP_TLS) -> list[str]:
    try:
        return ftp.nlst()
    except ftplib.error_perm:
        return []


def descargar_bytes(ftp: ftplib.FTP_TLS, nombre_archivo: str) -> bytes:
    buf = io.BytesIO()
    logger.info("Descargando %s", nombre_archivo)
    try:
        ftp.retrbinary(f"RETR {nombre_archivo}", buf.write)
    except ftplib.error_perm as e:
        logger.warning("Archivo no encontrado: %s (%s)", nombre_archivo, e)
        raise FTPFileNotFoundError(f"Archivo no encontrado: {nombre_archivo}: {e}")
    buf.seek(0)
    contenido = buf.read()
    logger.info("Descargado %s (%d bytes)", nombre_archivo, len(contenido))
    return contenido
