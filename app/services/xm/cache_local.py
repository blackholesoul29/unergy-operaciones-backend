"""Caché local de archivos crudos de XM, organizada por año — la misma
carpeta que la usuaria ya usa manualmente con FileZilla.

Si un archivo ya está en disco (de una descarga anterior por esta
pestaña, o bajado a mano con FileZilla), se reutiliza en vez de volver
a pedirlo al FTP — más rápido en rangos repetidos y menos carga sobre
el FTP de XM.

El agente local lo puede correr cualquiera del equipo con acceso al
FTP de XM, no solo Jessica — por eso el default de la carpeta depende
de qué usuario de Windows lo está corriendo: para Jessica, es la
carpeta de FileZilla que ya usa; para cualquier otro, una carpeta
genérica bajo su propio home. Se puede sobreescribir siempre con la
variable de entorno XM_CACHE_DIR (o un archivo .env en local_agent/).
"""
import getpass
import os
from pathlib import Path

CARPETA_BASE_DEFECTO_JESSICA = r"C:\Users\jessi\OneDrive\Documentos\Xm\Archivos_Filezilla"


def _usuario_actual() -> str:
    return getpass.getuser()


def carpeta_base() -> Path:
    override = os.getenv("XM_CACHE_DIR")
    if override:
        return Path(override)
    if _usuario_actual().lower() == "jessi":
        return Path(CARPETA_BASE_DEFECTO_JESSICA)
    return Path.home() / "Documentos" / "Xm" / "Archivos_Filezilla"


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
