"""Caché local de archivos crudos de XM, organizada por año — la misma
carpeta que la usuaria ya usa manualmente con FileZilla.

Si un archivo ya está en disco (de una descarga anterior por esta
pestaña, o bajado a mano con FileZilla), se reutiliza en vez de volver
a pedirlo al FTP — más rápido en rangos repetidos y menos carga sobre
el FTP de XM.
"""
import os
from pathlib import Path

CARPETA_BASE_DEFECTO = r"C:\Users\jessi\OneDrive\Documentos\Xm\Archivos_Filezilla"


def carpeta_base() -> Path:
    return Path(os.getenv("XM_CACHE_DIR", CARPETA_BASE_DEFECTO))


def ruta_cache(anio: int, nombre_archivo: str) -> Path:
    return carpeta_base() / str(anio) / nombre_archivo


def leer_si_existe(anio: int, nombre_archivo: str) -> bytes | None:
    ruta = ruta_cache(anio, nombre_archivo)
    if ruta.is_file():
        return ruta.read_bytes()
    return None


def guardar(anio: int, nombre_archivo: str, contenido: bytes) -> None:
    ruta = ruta_cache(anio, nombre_archivo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
