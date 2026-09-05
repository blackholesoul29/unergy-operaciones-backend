"""Hash de contraseñas y firma de tokens.

Portado de `app/core/security.py`. **Mismo algoritmo, misma clave y mismos
claims**: los tokens ya emitidos siguen siendo válidos y un usuario con sesión
abierta no nota la migración. Las contraseñas siguen en bcrypt, así que tampoco
hay que reestablecer ninguna.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

ALGORITMO = "HS256"
MINUTOS_POR_DEFECTO = 480
# La app móvil (PWA) usa un token largo para que nadie tenga que entrar a
# diario. Se revoca cambiando la contraseña.
MINUTOS_MOVIL = 43200
LARGO_MINIMO_CONTRASENA = 8


def _entero(nombre: str, defecto: int) -> int:
    crudo = os.environ.get(nombre, "")
    return int(crudo) if crudo.isdigit() else defecto


def clave_secreta() -> str:
    return os.environ.get("SECRET_KEY", "")


def hash_contrasena(contrasena: str) -> str:
    return bcrypt.hashpw(contrasena.encode(), bcrypt.gensalt()).decode()


def verificar_contrasena(plana: str, hasheada: str) -> bool:
    return bcrypt.checkpw(plana.encode(), hasheada.encode())


def crear_token(datos: dict, minutos: int | None = None) -> str:
    if minutos is None:
        minutos = _entero("JWT_EXPIRE_MINUTES", MINUTOS_POR_DEFECTO)
    payload = {
        **datos,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutos),
    }
    return jwt.encode(payload, clave_secreta(), algorithm=ALGORITMO)


def minutos_movil() -> int:
    return _entero("MOBILE_JWT_EXPIRE_MINUTES", MINUTOS_MOVIL)


def decodificar(token: str) -> dict | None:
    try:
        return jwt.decode(token, clave_secreta(), algorithms=[ALGORITMO])
    except JWTError:
        return None


def claims_de(usuario) -> dict:
    """Los cuatro claims del token. `sub` es el id, como cadena."""
    return {
        "sub": str(usuario.id),
        "rol": usuario.rol,
        "nombre": usuario.nombre,
        "email": usuario.email,
    }
