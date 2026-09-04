"""Sin token es 401, no 403 — en los dos backends.

`test_paridad_urls.py` compara qué RUTAS existen; no mira qué responden. Esta
divergencia se coló por ahí y afectaba a los 479 endpoints a la vez.

**Por qué pasa.** DRF degrada `NotAuthenticated` a 403 cuando el primer
autenticador de la vista no ofrece cabecera `WWW-Authenticate` (ver
`APIView.handle_exception`). Como ninguna de las dos clases la declaraba, todo
lo no autenticado salía 403 mientras FastAPI devolvía 401. El frontend
distingue los dos: con 403 mostraría "no tienes permiso" en vez de mandar a
iniciar sesión, y la sesión vencida dejaría al usuario mirando un error en vez
de volver al login.

La diferencia entre 401 y 403 se mantiene: 403 sigue siendo la respuesta cuando
el usuario SÍ está autenticado pero le falta el rol (`RolePermission`).
"""

import os

import pytest

# Uno por familia de recurso, no los 479: lo que se prueba es el comportamiento
# de las clases de autenticación, que son las mismas para todas las vistas.
RUTAS = [
    "/api/v1/proyectos",
    "/api/v1/clientes",
    "/api/v1/panel-contable",
    "/api/v1/liquidaciones",
    "/api/v1/fallas",
]


@pytest.fixture(scope="module")
def cliente():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    import django

    django.setup()
    from django.test import Client

    return Client()


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_token_es_401(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 401, (
        f"{ruta} respondió {respuesta.status_code}. Un 403 acá significa que se "
        "perdió el `authenticate_header` de `api/authentication.py`: sin él DRF "
        "degrada el 401 a 403 y el frontend deja de mandar al login."
    )


@pytest.mark.parametrize("ruta", RUTAS)
def test_con_token_invalido_es_401(cliente, ruta):
    respuesta = cliente.get(ruta, HTTP_AUTHORIZATION="Bearer no-es-un-token")
    assert respuesta.status_code == 401


def test_la_cabecera_no_dispara_el_dialogo_del_navegador(cliente):
    """`Basic` haría que el navegador abra su propio diálogo de usuario y
    contraseña sobre la aplicación. Tiene que ser `Bearer`."""
    respuesta = cliente.get(RUTAS[0])
    assert respuesta.headers.get("WWW-Authenticate") == "Bearer"


# No hay una prueba que compare contra FastAPI en vivo, y no es un olvido:
# `tests/conftest.py` anula `get_current_user` con `dependency_overrides` para
# todo el suite, así que ahí FastAPI devuelve 200 a una petición sin token. El
# 401 de referencia se verificó fuera de pytest, contra los dos servidores
# corriendo de verdad (2026-09-04). Meter acá un TestClient de FastAPI daría una
# comparación que pasa por el motivo equivocado.
