"""Orquesta un job completo de Descarga de XM: descarga -> unifica ->
(opcional) enriquece -> exporta. Corre dentro de un hilo en background
(ver api/v1/xm_descargas.py) porque ftplib es bloqueante."""
import logging
from concurrent.futures import ProcessPoolExecutor

from app.services.xm import jobs, tipos
from app.services.xm.downloader import ejecutar_descarga
from app.services.xm.exceptions import (
    FTPAuthenticationError, FTPConnectionError, FTPFileNotFoundError,
    FTPPermissionError, FTPTimeoutError,
)
from app.services.xm.ftp_client import conectar_ftp, descargar_bytes, listar_directorio
from app.services.xm.fronteras import obtener_fronteras_mes
from app.services.xm.unificador import enriquecer, exportar, nombre_salida, unificar

logger = logging.getLogger(__name__)

ERRORES_FTP = (FTPConnectionError, FTPAuthenticationError, FTPPermissionError,
               FTPFileNotFoundError, FTPTimeoutError)

CODIGO_ERROR = {
    "FTPConnectionError": "FTP_CONNECTION_FAILED",
    "FTPAuthenticationError": "FTP_AUTH_FAILED",
    "FTPPermissionError": "FTP_PERMISSION_DENIED",
    "FTPFileNotFoundError": "FTP_FILE_NOT_FOUND",
    "FTPTimeoutError": "FTP_TIMEOUT",
}


_pool_exportar = None


def _pool():
    """Escribir un .xlsx grande (openpyxl/xlsxwriter) es lento — ~100s para
    ~250k filas, sin importar el motor, porque cada celda se serializa a
    XML. Ese trabajo es puro CPU en Python y acapara el GIL: si corre en
    un hilo del mismo proceso que atiende el servidor HTTP, el sondeo de
    estado del frontend deja de recibir respuesta a tiempo aunque el job
    siga avanzando bien. Se delega a un proceso aparte para que el
    servidor HTTP no se congele mientras tanto."""
    global _pool_exportar
    if _pool_exportar is None:
        _pool_exportar = ProcessPoolExecutor(max_workers=1)
    return _pool_exportar


def _listar_fn(ftp_params, directorio):
    ftp = conectar_ftp(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], directorio)
    try:
        return listar_directorio(ftp)
    finally:
        ftp.quit()


def _descargar_fn(ftp_params, directorio, nombre):
    ftp = conectar_ftp(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], directorio)
    try:
        return descargar_bytes(ftp, nombre)
    finally:
        ftp.quit()


def ejecutar_job(job_id: str, ftp_params: dict, tipo: str, extension: str,
                  fecha_inicio, fecha_fin, enriquecer_flag: bool) -> None:
    logger.info(
        "Job %s: iniciando %s %s, %s a %s, enriquecer=%s",
        job_id, tipo, extension, fecha_inicio, fecha_fin, enriquecer_flag,
    )
    try:
        def on_progreso(hechos, totales):
            jobs.actualizar_job(job_id, archivos_procesados=hechos, archivos_totales=totales)

        archivos, faltantes = ejecutar_descarga(
            ftp_params, tipo, extension, fecha_inicio, fecha_fin, on_progreso=on_progreso,
        )
        logger.info("Job %s: descarga terminada, pasando a unificar", job_id)
        jobs.actualizar_job(job_id, estado="unificando", archivos_faltantes=faltantes)

        df = unificar(tipo, archivos)
        logger.info("Job %s: unificado, %d filas", job_id, len(df))
        codigos_sin_match: list[str] = []
        meses_usados: dict = {}

        if enriquecer_flag and tipo in tipos.TIPOS_ENRIQUECIBLES and not df.empty:
            meses = sorted({fecha_doc[:7] for fecha_doc, _ in archivos})
            logger.info("Job %s: enriqueciendo, meses a buscar en fronteras: %s", job_id, meses)
            fronteras_por_mes = {}
            for mes_str in meses:
                anio, mes = int(mes_str[:4]), int(mes_str[5:7])
                tabla, mes_usado, archivo_usado = obtener_fronteras_mes(
                    lambda d, _fp=ftp_params: _listar_fn(_fp, d),
                    lambda d, n, _fp=ftp_params: _descargar_fn(_fp, d, n),
                    anio, mes,
                )
                fronteras_por_mes[mes_str] = tabla
                meses_usados[mes_str] = {"mes_usado": mes_usado, "archivo": archivo_usado}

            columna = tipos.COLUMNA_CODIGO_ENRIQUECIMIENTO[tipo]
            df, sin_match_set = enriquecer(df, tipo, fronteras_por_mes, columna)
            codigos_sin_match = sorted(sin_match_set)
            logger.info("Job %s: enriquecimiento listo, %d códigos sin match", job_id, len(codigos_sin_match))

        nombre_xlsx, nombre_txt = nombre_salida(tipo, extension, fecha_inicio, fecha_fin)
        logger.info("Job %s: exportando %d filas a Excel/TXT (puede tardar con archivos grandes)", job_id, len(df))
        jobs.actualizar_job(job_id, estado="exportando")
        bytes_xlsx, bytes_txt = _pool().submit(exportar, df).result()
        logger.info("Job %s: listo (%s, %d bytes)", job_id, nombre_xlsx, len(bytes_xlsx))

        jobs.actualizar_job(
            job_id, estado="listo",
            codigos_sin_match=codigos_sin_match,
            meses_fronteras_usados=meses_usados,
            resultado={
                "nombre_xlsx": nombre_xlsx, "bytes_xlsx": bytes_xlsx,
                "nombre_txt": nombre_txt, "bytes_txt": bytes_txt,
            },
        )
    except ERRORES_FTP as e:
        logger.warning("Job %s: error FTP (%s): %s", job_id, type(e).__name__, e)
        jobs.actualizar_job(
            job_id, estado="error",
            error_code=CODIGO_ERROR.get(type(e).__name__, type(e).__name__),
            error_message=str(e),
        )
    except Exception as e:
        logger.exception("Job %s: error interno inesperado", job_id)
        jobs.actualizar_job(job_id, estado="error", error_code="INTERNAL_ERROR", error_message=str(e))
