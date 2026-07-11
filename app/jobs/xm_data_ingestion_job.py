"""Job programado: ingesta diaria de archivos XM.

Escanea el directorio configurado (`XM_INCOMING_FILES_PATH`), procesa cada
Excel con el servicio de ingesta y, si el procesamiento es exitoso, mueve el
archivo al directorio de archivo (`XM_ARCHIVE_FILES_PATH`). Es idempotente: la
deduplicación por `hash_fila` evita insertar filas repetidas si un archivo se
reprocesa.

Se ejecuta desde el scheduler de `app.main` (BackgroundScheduler, basado en
hilos), por eso `run_daily_xm_ingestion` es una función síncrona normal.
"""
import logging
import os
import shutil
from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import xm_ingestion_service

logger = logging.getLogger(__name__)

_EXTENSIONES = (".xlsx", ".xls")


def _archivar(file_path: str, archive_dir: str) -> None:
    """Mueve un archivo procesado al directorio de archivo (sin sobrescribir)."""
    os.makedirs(archive_dir, exist_ok=True)
    nombre = os.path.basename(file_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(nombre)
    destino = os.path.join(archive_dir, f"{base}__{stamp}{ext}")
    shutil.move(file_path, destino)


def run_daily_xm_ingestion() -> dict:
    """Procesa todos los archivos XM pendientes en el directorio de entrada.

    Devuelve un resumen agregado del corrido.
    """
    incoming = settings.XM_INCOMING_FILES_PATH
    archive = settings.XM_ARCHIVE_FILES_PATH

    resumen = {
        "directorio": incoming,
        "archivos_procesados": 0,
        "archivos_con_error": 0,
        "filas_nuevas": 0,
        "detalles": [],
    }

    if not incoming or not os.path.isdir(incoming):
        logger.info("[xm_ingestion_job] Directorio de entrada no existe: %s", incoming)
        return resumen

    archivos = sorted(
        f for f in os.listdir(incoming)
        if f.lower().endswith(_EXTENSIONES) and not f.startswith("~$")
    )
    if not archivos:
        logger.info("[xm_ingestion_job] Sin archivos nuevos en %s", incoming)
        return resumen

    for nombre in archivos:
        ruta = os.path.join(incoming, nombre)
        if not os.path.isfile(ruta):
            continue
        db = SessionLocal()
        try:
            detalle = xm_ingestion_service.process_xm_file(db, ruta)
            resumen["archivos_procesados"] += 1
            resumen["filas_nuevas"] += detalle.get("filas_nuevas", 0)
            resumen["detalles"].append(detalle)
            _archivar(ruta, archive)
            logger.info(
                "[xm_ingestion_job] %s procesado (nuevas=%s) y archivado",
                nombre, detalle.get("filas_nuevas"),
            )
        except Exception as e:  # noqa: BLE001 — un archivo malo no detiene los demás
            db.rollback()
            resumen["archivos_con_error"] += 1
            resumen["detalles"].append({"fuente_archivo": nombre, "error": str(e)})
            logger.error("[xm_ingestion_job] Falló %s: %s", nombre, e)
        finally:
            db.close()

    logger.info(
        "[xm_ingestion_job] Fin: procesados=%s errores=%s filas_nuevas=%s",
        resumen["archivos_procesados"], resumen["archivos_con_error"], resumen["filas_nuevas"],
    )
    return resumen
