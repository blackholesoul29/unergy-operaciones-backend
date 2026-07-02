"""Descarga con reintentos/reconexión sobre el plan de plan_descarga.

conectar_fn/descargar_fn/sleep_fn son inyectables para poder testear la
lógica de reintentos y progreso sin tocar la red real; en producción son
ftp_client.conectar_ftp / ftp_client.descargar_bytes / time.sleep.
"""
import time

from app.services.xm.ftp_client import conectar_ftp, descargar_bytes
from app.services.xm.plan_descarga import construir_plan_descarga


def ejecutar_descarga(ftp_params: dict, tipo: str, extension: str, fecha_inicio, fecha_fin,
                       on_progreso=None, max_reintentos: int = 3, espera_reintento: int = 10,
                       conectar_fn=conectar_ftp, descargar_fn=descargar_bytes, sleep_fn=time.sleep):
    plan = construir_plan_descarga(tipo, extension, fecha_inicio, fecha_fin)
    archivos = []
    faltantes = []
    ftp = None
    directorio_actual = None

    for i, item in enumerate(plan):
        if ftp is None or directorio_actual != item["directorio"]:
            ftp = conectar_fn(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], item["directorio"])
            directorio_actual = item["directorio"]

        contenido = None
        for intento in range(max_reintentos):
            try:
                contenido = descargar_fn(ftp, item["nombre_archivo"])
                break
            except Exception:
                if intento < max_reintentos - 1:
                    sleep_fn(espera_reintento)
                    ftp = conectar_fn(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], item["directorio"])
                    directorio_actual = item["directorio"]

        if contenido is None:
            faltantes.append(item["nombre_archivo"])
        else:
            archivos.append((item["fecha_documento"], contenido))

        if on_progreso:
            on_progreso(i + 1, len(plan))

    return archivos, faltantes
