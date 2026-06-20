"""Carga las credenciales del backend Unergy desde el entorno.

No se hardcodean secretos en el código. Define las variables en un archivo
``.env`` (ver ``.env.example``) o expórtalas antes de ejecutar los scripts de
carga (``scripts/cargar_*.py``, ``reconciliar_*.py``, ``migrate_*.py``):

    UNERGY_API_EMAIL=tu-usuario@unergy.io
    UNERGY_API_PASS=tu-password
"""
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # python-dotenv es opcional: las vars pueden venir del entorno
    pass


def api_credentials():
    """Devuelve ``(email, password)`` desde el entorno. Aborta si falta alguna."""
    email = os.environ.get("UNERGY_API_EMAIL")
    password = os.environ.get("UNERGY_API_PASS")
    faltantes = [
        nombre
        for nombre, valor in (
            ("UNERGY_API_EMAIL", email),
            ("UNERGY_API_PASS", password),
        )
        if not valor
    ]
    if faltantes:
        sys.exit(
            "ERROR: faltan variables de entorno requeridas: "
            + ", ".join(faltantes)
            + ".\nDefínelas en un archivo .env o expórtalas antes de ejecutar "
            "el script (ver .env.example)."
        )
    return email, password
