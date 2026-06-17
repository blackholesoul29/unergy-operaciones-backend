"""Utilidades de contraseñas seguras.

Módulo puro (sin dependencias de FastAPI ni de la base de datos) para poder
probarlo de forma aislada. Reúne tres responsabilidades:

  1. `generate_secure_password()` — genera contraseñas aleatorias fuertes con
     `secrets` (NO `random`), garantizando las cuatro clases de caracteres.
  2. `validate_password_strength()` — política de complejidad para las
     contraseñas que elige el usuario al cambiarlas.
  3. `needs_password_reset()` — decide si una petición debe bloquearse porque el
     usuario tiene `force_password_reset` activo.

`hash_password` se re-exporta de forma perezosa desde `app.core.security` para
no acoplar este módulo (ni sus tests) a bcrypt salvo cuando realmente se usa.
"""
from __future__ import annotations

import secrets
import string

# Conjuntos de caracteres por clase. Excluimos caracteres ambiguos no aporta
# seguridad real y complica el soporte; mantenemos el alfabeto completo.
_UPPER = string.ascii_uppercase
_LOWER = string.ascii_lowercase
_DIGITS = string.digits
_SPECIAL = "!@#$%^&*()-_=+[]{};:,.?"

_ALL = _UPPER + _LOWER + _DIGITS + _SPECIAL

# Mínimo absoluto: 4 para poder colocar una de cada clase.
_MIN_GENERATED_LENGTH = 12
_MIN_USER_LENGTH = 10

# Rutas que un usuario con `force_password_reset` SÍ puede usar (para poder
# salir del estado de bloqueo). Se comparan por sufijo para ser robustos al
# prefijo `/api/v1`.
_RESET_ALLOWED_SUFFIXES = (
    "/auth/change-password",
    "/auth/me",
    "/auth/token",
    "/auth/logout",
)


def generate_secure_password(length: int = 16) -> str:
    """Genera una contraseña aleatoria criptográficamente fuerte.

    Garantiza al menos una mayúscula, una minúscula, un dígito y un carácter
    especial. Usa `secrets` (CSPRNG), nunca `random`.
    """
    if length < _MIN_GENERATED_LENGTH:
        raise ValueError(
            f"length debe ser >= {_MIN_GENERATED_LENGTH} para garantizar complejidad"
        )

    # Una de cada clase para garantizar la complejidad…
    required = [
        secrets.choice(_UPPER),
        secrets.choice(_LOWER),
        secrets.choice(_DIGITS),
        secrets.choice(_SPECIAL),
    ]
    # …y el resto del alfabeto completo.
    remaining = [secrets.choice(_ALL) for _ in range(length - len(required))]

    chars = required + remaining
    # Barajado seguro (Fisher–Yates con secrets) — `random.shuffle` no es seguro.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """Valida la complejidad de una contraseña elegida por el usuario.

    Devuelve `(True, None)` si cumple, o `(False, motivo)` en español si no.
    Requisitos: longitud mínima y al menos 3 de las 4 clases de caracteres.
    """
    if not password or len(password) < _MIN_USER_LENGTH:
        return False, f"La contraseña debe tener al menos {_MIN_USER_LENGTH} caracteres"

    classes = sum(
        bool(set(password) & set(charset))
        for charset in (_UPPER, _LOWER, _DIGITS, _SPECIAL)
    )
    if classes < 3:
        return False, (
            "La contraseña debe combinar al menos 3 de: mayúsculas, minúsculas, "
            "números y símbolos"
        )
    return True, None


def needs_password_reset(force_flag: bool, path: str) -> bool:
    """¿Debe bloquearse esta petición por contraseña pendiente de cambio?

    True si el usuario tiene `force_password_reset` y la ruta no es una de las
    permitidas para salir del bloqueo.
    """
    if not force_flag:
        return False
    return not any(path.endswith(suffix) for suffix in _RESET_ALLOWED_SUFFIXES)


def hash_password(password: str) -> str:
    """Re-exporta `app.core.security.hash_password` de forma perezosa."""
    from app.core.security import hash_password as _hash_password

    return _hash_password(password)
