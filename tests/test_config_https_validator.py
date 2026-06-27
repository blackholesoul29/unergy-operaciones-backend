"""Tests del validador que exige HTTPS en URLs de servicios externos críticos.

El validador `external_url_must_be_https` (app/core/config.py) hace que la app
falle al arrancar si una variable de entorno trae una URL insegura (http:// u
otro esquema) para un servicio externo. Una cadena vacía = servicio no
configurado y se permite.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Los 8 campos protegidos por el validador.
PROTECTED_FIELDS = [
    "UNERGY_API_URL",
    "SUNFACTORY_API_URL",
    "SUNFACTORY_AUTH_URL",
    "SOLENIUM_AUTH_URL",
    "SOLENIUM_DATA_URL",
    "QUOIA_BASE_URL",
    "GAIA_BASE_URL",
    "EVO_API_URL",
]


@pytest.mark.parametrize("field", PROTECTED_FIELDS)
def test_http_url_is_rejected(field):
    # Una URL http:// en cualquier campo crítico debe abortar el arranque.
    with pytest.raises(ValidationError) as exc:
        Settings(**{field: "http://api.unergy.io"})
    # El mensaje (en español) nombra el campo ofensor para un diagnóstico accionable.
    assert field in str(exc.value)
    assert "HTTPS" in str(exc.value)
    assert "interno" in str(exc.value).lower()


@pytest.mark.parametrize("field", PROTECTED_FIELDS)
def test_https_url_is_accepted(field):
    s = Settings(**{field: "https://api.example.com"})
    assert getattr(s, field) == "https://api.example.com"


@pytest.mark.parametrize("field", PROTECTED_FIELDS)
def test_empty_string_is_accepted(field):
    # Servicio no configurado: cadena vacía permitida.
    s = Settings(**{field: ""})
    assert getattr(s, field) == ""


def test_non_http_scheme_is_rejected():
    # Cualquier esquema que no sea https debe rechazarse (no solo http).
    with pytest.raises(ValidationError):
        Settings(UNERGY_API_URL="ftp://api.unergy.io")
    with pytest.raises(ValidationError):
        Settings(UNERGY_API_URL="api.unergy.io")  # sin esquema


def test_https_scheme_is_case_insensitive():
    # El esquema de URL es case-insensitive (RFC 3986); HTTPS:// debe aceptarse,
    # de lo contrario una mayúscula legítima en una env var abortaría el arranque.
    s = Settings(UNERGY_API_URL="HTTPS://api.unergy.io")
    assert s.UNERGY_API_URL == "HTTPS://api.unergy.io"


@pytest.mark.parametrize(
    "url",
    [
        "http://100.101.33.118:18800",  # Tailscale CGNAT (caso real del EVO)
        "http://localhost:18800",
        "http://127.0.0.1:8000",
        "http://10.0.0.5:9000",         # RFC1918
        "http://192.168.1.50",          # RFC1918
        "http://172.16.4.4:8080",       # RFC1918
        "http://evo:18800",             # etiqueta única (servicio docker/k8s)
        "http://evo.internal:18800",    # sufijo DNS interno
        "http://evo.local",             # mDNS
        "http://evo-x2.tail1234.ts.net",  # Tailscale MagicDNS
    ],
)
def test_http_internal_host_is_allowed(url):
    # http:// a un host interno (loopback/privado/Tailscale) NO debe abortar el
    # arranque: ese tráfico no transita la Internet pública.
    s = Settings(EVO_API_URL=url)
    assert s.EVO_API_URL == url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.unergy.io",     # hostname público
        "http://8.8.8.8",           # IP pública
        "http://sunfactory.solenium.co/api",
    ],
)
def test_http_public_host_is_rejected(url):
    # http:// a un host público sí debe abortar — eso es plaintext en Internet.
    with pytest.raises(ValidationError):
        Settings(EVO_API_URL=url)


def test_settings_construct_without_raising():
    # Regresión: el arranque no debe abortar con la config real. El EVO se
    # configura como http:// sobre Tailscale (CGNAT 100.x); el validador debe
    # aceptarlo. Construir Settings() no debe lanzar ValidationError.
    Settings()  # no raise

    # Y un default https explícito sigue siendo válido.
    s = Settings(UNERGY_API_URL="https://api.unergy.io")
    assert s.UNERGY_API_URL == "https://api.unergy.io"
