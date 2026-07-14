"""Estado de las migraciones del último arranque.

`start.sh` corre `alembic upgrade heads` y, si falla, deja una marca en disco y
arranca el servidor igual (crash-loopear el deploy es peor que un backend
degradado). El proceso vive, pero el esquema puede estar VIEJO.

Sin esta señal el fallo es invisible: el contenedor queda verde, `/health`
responde "ok" y la API sirve datos con el esquema equivocado. Nadie lee los logs
del contenedor; todos miran el health check.
"""
import os

MARCA_POR_DEFECTO = "/tmp/migraciones_fallidas"


def _ruta_marca() -> str:
    return os.environ.get("MIGRACIONES_FALLIDAS_FILE", MARCA_POR_DEFECTO)


def migraciones_fallaron() -> bool:
    """True si el último arranque NO pudo aplicar las migraciones."""
    return os.path.exists(_ruta_marca())


def estado_salud(app_name: str) -> dict:
    """Cuerpo de `/health`.

    Sigue devolviendo HTTP 200 (el proceso está vivo y responde), pero deja de
    decir "ok" cuando el esquema puede estar desactualizado.
    """
    if migraciones_fallaron():
        return {
            "status": "degraded",
            "app": app_name,
            "migraciones": "NO aplicadas — el esquema puede estar desactualizado",
        }
    return {"status": "ok", "app": app_name}
