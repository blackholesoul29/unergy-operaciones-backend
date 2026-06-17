"""Tests de seguridad de contraseñas.

Cubre:
  1. Generación de contraseñas fuertes (complejidad + aleatoriedad).
  2. Política de complejidad para contraseñas elegidas por el usuario.
  3. Decisión de bloqueo por `force_password_reset`.
  4. Que el modelo `Usuario` fuerza el reset por defecto.
  5. Que ya NO hay credenciales hardcodeadas en seed ni en el script de migración.

Son tests puros/estáticos a propósito: el `conftest.py` del repo stubea
`app.api.v1.auth` para evitar la cadena de imports de seguridad, así que la
lógica testeable vive en `app/utils/password_generator.py` (no stubeado).
"""
import os
import re
import string

import pytest

from app.utils.password_generator import (
    generate_secure_password,
    validate_password_strength,
    needs_password_reset,
    _SPECIAL,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 1. Generación ──────────────────────────────────────────────────────────


def test_generated_password_has_default_length():
    assert len(generate_secure_password()) == 16


def test_generated_password_respects_custom_length():
    assert len(generate_secure_password(24)) == 24


def test_generated_password_meets_all_classes():
    for _ in range(200):  # muestreo: la garantía debe cumplirse SIEMPRE
        pw = generate_secure_password()
        assert any(c in string.ascii_uppercase for c in pw), pw
        assert any(c in string.ascii_lowercase for c in pw), pw
        assert any(c in string.digits for c in pw), pw
        assert any(c in _SPECIAL for c in pw), pw


def test_generated_passwords_are_unique():
    pws = {generate_secure_password() for _ in range(500)}
    assert len(pws) == 500  # colisión ⇒ generador no aleatorio


def test_generated_password_rejects_too_short():
    with pytest.raises(ValueError):
        generate_secure_password(8)


def test_generator_does_not_use_insecure_random():
    src = open(
        os.path.join(_REPO_ROOT, "app", "utils", "password_generator.py"),
        encoding="utf-8",
    ).read()
    assert "import secrets" in src
    assert re.search(r"^\s*import random", src, re.MULTILINE) is None


# ── 2. Política de complejidad ──────────────────────────────────────────────


def test_validate_rejects_short():
    ok, msg = validate_password_strength("Ab1!")
    assert ok is False and msg


def test_validate_rejects_low_diversity():
    ok, _ = validate_password_strength("abcdefghijklmnop")  # solo minúsculas
    assert ok is False


def test_validate_accepts_strong():
    ok, msg = validate_password_strength("MiClaveSegura9!")
    assert ok is True and msg is None


def test_validate_accepts_generated():
    ok, _ = validate_password_strength(generate_secure_password())
    assert ok is True


# ── 3. Bloqueo por reset pendiente ──────────────────────────────────────────


def test_needs_reset_blocks_normal_endpoint():
    assert needs_password_reset(True, "/api/v1/proyectos") is True


def test_needs_reset_allows_change_password():
    assert needs_password_reset(True, "/api/v1/auth/change-password") is False


def test_needs_reset_allows_me_and_token():
    assert needs_password_reset(True, "/api/v1/auth/me") is False
    assert needs_password_reset(True, "/api/v1/auth/token") is False


def test_no_reset_when_flag_false():
    assert needs_password_reset(False, "/api/v1/proyectos") is False


# ── 4. Modelo Usuario ───────────────────────────────────────────────────────


def test_usuario_model_has_reset_fields_defaulting_true():
    from app.models.usuarios import Usuario

    cols = Usuario.__table__.columns
    assert "force_password_reset" in cols
    assert "password_changed_at" in cols
    # Default a nivel Python = True
    assert cols["force_password_reset"].default.arg is True


# ── 5. Sin credenciales hardcodeadas ────────────────────────────────────────

_LEAKED = "Unergy2025!"


def test_seed_has_no_hardcoded_password():
    src = open(
        os.path.join(_REPO_ROOT, "app", "seeds", "seed_data.py"), encoding="utf-8"
    ).read()
    assert _LEAKED not in src
    assert "generate_secure_password" in src
    assert "force_password_reset=True" in src


def test_migrate_script_has_no_hardcoded_credentials():
    src = open(
        os.path.join(_REPO_ROOT, "migrate_fallas_desde_sheets.py"), encoding="utf-8"
    ).read()
    assert _LEAKED not in src
    # La contraseña/usuario deben venir del entorno, no del código.
    assert "os.environ" in src or "getenv" in src
