"""Generación y verificación de claves de API.

Vive en el dominio y no en la vista porque la verificación la necesita también
`api/authentication.py` cuando se agregue la autenticación por API key, y
generar la clave en dos sitios es como se acaban con dos formatos de prefijo.
"""

import hashlib
import secrets

PREFIJO = "uop_"
LARGO_PREFIJO_VISIBLE = 12


def hash_de_clave(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def generar_clave() -> tuple[str, str, str]:
    """Devuelve (clave en claro, hash, prefijo visible).

    La clave en claro se entrega UNA sola vez, al crearla. Después solo queda el
    hash: no hay forma de recuperarla, y eso es a propósito.
    """
    clave = f"{PREFIJO}{secrets.token_hex(32)}"
    return clave, hash_de_clave(clave), clave[:LARGO_PREFIJO_VISIBLE]
