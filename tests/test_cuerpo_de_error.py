"""El cuerpo de error va SIEMPRE bajo `detail`, sea texto o dict.

Bug real (2026-09-05): al agregar la frontera de San Luis de Since desde
"Fronteras nuevas en Quoia", la pantalla decia "No se pudo agregar la frontera"
y no daba salida. El backend en realidad estaba avisando que existia una
frontera con nombre parecido -- un 409 reintentable con `?forzar=true` -- pero
el aviso llegaba sin su mensaje.

La causa es el manejador por defecto de DRF:

    data = exc.detail if isinstance(exc.detail, (list, dict))
           else {"detail": exc.detail}

Un `detail` de texto sale como `{"detail": "..."}`; uno de tipo dict sale CRUDO
en la raiz. FastAPI ponia los dos bajo `detail`, y el frontend lee
`e.data.detail` en ambos casos: contra el dict leia `undefined`. Ademas
`APIException` aplasta cada valor del dict a `ErrorDetail` (subclase de `str`),
asi que `True` viajaba como `"True"` y `7` como `"7"`.

No era solo de fronteras: `Conflict(dict)` / `NoProcesable(dict)` los usan
clientes, comercial, proyectos, operadores, facturacion y finanzas_mandatos.
En todos el usuario veia un error generico en vez de la explicacion.

`api.exceptions.manejador_de_excepciones` lo repone. Este test fija las cuatro
esquinas del contrato, incluida la que NO debe cambiar: el dict de errores por
campo de `ValidationError` sigue crudo en la raiz, que es lo que el frontend ya
consume para los 400.
"""
import pytest

pytest.importorskip("django", reason="requiere el entorno de Django (uv sync)")


@pytest.fixture(scope="module", autouse=True)
def _django_listo():
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    django.setup()


AVISO = {
    "mensaje": "Ya existe una frontera con un nombre muy parecido: 'X' (ID 7).",
    "duplicado_nombre": True,
    "candidato_id": 7,
    "candidato_nombre": "X",
}


def _manejar(exc):
    from api.exceptions import manejador_de_excepciones

    return manejador_de_excepciones(exc, {})


def test_el_dict_va_bajo_detail_no_crudo_en_la_raiz():
    """Es exactamente lo que fallaba: el frontend lee `e.data.detail`."""
    from api.exceptions import Conflict

    respuesta = _manejar(Conflict(AVISO))

    assert respuesta.status_code == 409
    assert list(respuesta.data) == ["detail"], (
        "el cuerpo salio crudo en la raiz: el cliente lee e.data.detail y "
        "encuentra undefined, asi que muestra un error generico sin salida"
    )
    assert respuesta.data["detail"]["mensaje"] == AVISO["mensaje"]


def test_los_valores_conservan_su_tipo():
    """DRF los aplasta a str: `duplicado_nombre` llegaba como "True"."""
    from api.exceptions import Conflict

    detalle = _manejar(Conflict(AVISO)).data["detail"]

    assert detalle["duplicado_nombre"] is True
    assert detalle["candidato_id"] == 7


def test_el_texto_simple_sigue_igual():
    """No se rompe el caso que ya funcionaba."""
    from api.exceptions import Conflict

    respuesta = _manejar(Conflict("Ya existe una frontera con ese codigo_frontera"))

    assert respuesta.data == {"detail": "Ya existe una frontera con ese codigo_frontera"}


def test_tambien_aplica_a_no_procesable():
    """`NoProcesable(dict)` lo usan facturacion, comercial y finanzas_mandatos."""
    from api.exceptions import NoProcesable

    respuesta = _manejar(NoProcesable({"periodo": "mal formado"}))

    assert respuesta.status_code == 422
    assert respuesta.data == {"detail": {"periodo": "mal formado"}}


def test_la_validacion_de_drf_NO_se_toca():
    """El dict de errores por campo va crudo en la raiz a proposito: es el
    contrato que el frontend ya consume para los 400. Envolverlo aca romperia
    todos los formularios."""
    from rest_framework.exceptions import ValidationError

    respuesta = _manejar(ValidationError({"nombre": ["Requerido"]}))

    assert respuesta.status_code == 400
    assert "detail" not in respuesta.data
    assert respuesta.data["nombre"] == ["Requerido"]
