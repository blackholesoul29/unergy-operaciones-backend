"""Postura de seguridad de config al arranque: ENVIRONMENT validado + SECRET_KEY con dientes.

Contexto (auditoría Nightwatch 2026-07-04): `settings.SECRET_KEY` firma/verifica los
JWT (app/core/security.py). Si un deploy de producción olvida `ENVIRONMENT`, antes se
trataba como 'development' y un SECRET_KEY vacío/débil solo advertía → tokens de auth
forjables. Ahora `ENVIRONMENT` es obligatorio y validado contra una allowlist, y
`production` exige un SECRET_KEY no vacío. Estos tests fijan ambos comportamientos y,
en particular, que el caso AUSENTE devuelva el mensaje accionable en español (no el
"Field required" genérico de pydantic).
"""
import warnings

import pytest
from pydantic import ValidationError

from app.core.config import ALLOWED_ENVIRONMENTS, Settings

_STRONG = "x" * 40  # SECRET_KEY fuerte (>= 32 chars)


def _make(**over):
    """Construye Settings sin heredar el .env local: fija solo los campos relevantes.

    `_env_file=None` evita que pydantic-settings lea el .env del repo (que trae
    ENVIRONMENT=development), así cada test controla el valor bajo prueba.
    """
    kwargs = {"SECRET_KEY": _STRONG}
    kwargs.update(over)
    return Settings(_env_file=None, **kwargs)


def test_missing_environment_gives_actionable_spanish_error(monkeypatch):
    # El caso estelar: prod olvida ENVIRONMENT. Debe fallar con mensaje en español
    # que nombre los valores válidos y dónde setearla — no el "Field required" inglés.
    # conftest fija ENVIRONMENT en os.environ; lo removemos para simular la AUSENCIA
    # real (pydantic-settings lee env vars aunque _env_file=None).
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError) as exc:
        _make()  # ENVIRONMENT ausente → cae al default centinela ""
    msg = str(exc.value)
    assert "ENVIRONMENT" in msg
    assert "Railway" in msg
    assert "production" in msg


def test_invalid_environment_rejected():
    with pytest.raises(ValidationError):
        _make(ENVIRONMENT="prod")  # typo — no está en la allowlist


def test_environment_is_case_and_space_insensitive():
    s = _make(ENVIRONMENT="  Production ", SECRET_KEY=_STRONG)
    assert s.ENVIRONMENT == "production"  # normalizado a canónico


def test_production_rejects_empty_secret_key():
    with pytest.raises(ValidationError):
        _make(ENVIRONMENT="production", SECRET_KEY="")


def test_production_accepts_strong_secret_key():
    assert _make(ENVIRONMENT="production", SECRET_KEY=_STRONG).ENVIRONMENT == "production"


def test_development_allows_empty_secret_key_with_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        s = _make(ENVIRONMENT="development", SECRET_KEY="")
    assert s.ENVIRONMENT == "development"
    assert any("SECRET_KEY" in str(w.message) for w in caught)


def test_allowed_environments_are_the_expected_three():
    assert ALLOWED_ENVIRONMENTS == ("development", "staging", "production")
