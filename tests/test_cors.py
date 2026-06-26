"""CORS — orígenes de confianza.

Contexto: el monitoreo se sirve desde Railway y se embebe como iframe en la
plataforma (Vercel u otro dominio). El origen puede ser cualquier subdominio de
`*.vercel.app` (previews/producción), `*.unergy.io` (dominios propios) o un
dominio custom configurado explícitamente. La auth es JWT en el header
Authorization (no cookies), pero igual restringimos CORS a sufijos de confianza
en vez de aceptar CUALQUIER origen HTTPS (`https://.*`), que un escáner marca
como permisivo y que no aporta nada legítimo.

Estos tests fijan dos invariantes:
  1. El regex por defecto acepta los dominios documentados y RECHAZA cualquier
     otro (incl. intentos de sufijo tipo `unergy.io.evil.com`).
  2. La lista explícita de orígenes incluye FRONTEND_URL + localhost + extras de
     FRONTEND_ORIGINS, sin duplicados, sin que un default vacío rompa producción.

Starlette empareja `allow_origin_regex` con `re.fullmatch`, así que los tests
usan fullmatch para reflejar el comportamiento real del middleware.
"""
import re

from app.core.config import Settings


def _settings(**kw) -> Settings:
    # _env_file=None aísla del .env del repo para tests deterministas.
    return Settings(_env_file=None, **kw)


def _regex(s: Settings) -> re.Pattern:
    return re.compile(s.CORS_ALLOWED_ORIGIN_REGEX)


# ── 1. regex de sufijos de confianza ────────────────────────────────────────
def test_regex_accepts_trusted_origins():
    rx = _regex(_settings())
    for origin in (
        "https://operaciones.unergy.io",
        "https://unergy.io",
        "https://app-git-feature-team.vercel.app",
        "https://unergy-operaciones.vercel.app",
    ):
        assert rx.fullmatch(origin), f"debería aceptar {origin}"


def test_regex_rejects_untrusted_and_lookalike_origins():
    rx = _regex(_settings())
    for origin in (
        "https://evil.com",
        "https://unergy.io.evil.com",   # sufijo falsificado
        "https://evilunergy.io",        # sin separador de subdominio
        "https://notvercel.app",        # sin separador de subdominio
        "http://operaciones.unergy.io",  # no-HTTPS
    ):
        assert not rx.fullmatch(origin), f"NO debería aceptar {origin}"


def test_regex_is_not_a_wildcard():
    # Regresión: el bug original aceptaba cualquier https:// .
    rx = _regex(_settings())
    assert not rx.fullmatch("https://anything.example.org")


# ── 2. lista explícita de orígenes ───────────────────────────────────────────
def test_allow_origins_includes_frontend_url_and_localhost():
    origins = _settings(FRONTEND_URL="https://operaciones.unergy.io").cors_allow_origins
    assert "https://operaciones.unergy.io" in origins
    assert "http://localhost:5173" in origins
    assert "http://localhost:3000" in origins


def test_allow_origins_parses_frontend_origins_csv():
    origins = _settings(
        FRONTEND_URL="http://localhost:5173",
        FRONTEND_ORIGINS="https://app.cliente.com, https://otro.io ,",
    ).cors_allow_origins
    assert "https://app.cliente.com" in origins
    assert "https://otro.io" in origins
    # entradas vacías por comas finales descartadas
    assert "" not in origins


def test_allow_origins_dedupes_and_drops_empty():
    origins = _settings(
        FRONTEND_URL="http://localhost:5173",  # duplica el localhost base
        FRONTEND_ORIGINS="",
    ).cors_allow_origins
    assert origins.count("http://localhost:5173") == 1
    assert all(o for o in origins)


def test_empty_config_does_not_strand_production_via_regex():
    # Con default vacío de FRONTEND_ORIGINS, los frontends de producción siguen
    # permitidos por el regex de sufijos (no quedan bloqueados).
    s = _settings(FRONTEND_ORIGINS="")
    rx = _regex(s)
    assert rx.fullmatch("https://operaciones.unergy.io")
    assert rx.fullmatch("https://unergy-ops.vercel.app")
