"""Excepciones DRF que faltan para reproducir el contrato actual.

FastAPI permite `HTTPException(409, {...})` con un cuerpo arbitrario, y varios
endpoints lo usan para devolver un aviso de duplicado con los datos del
candidato. DRF no trae un `Conflict`, así que se declara acá una sola vez en vez
de armar `Response(status=409)` a mano en cada vista.
"""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as manejador_drf


class CuerpoPropio(APIException):
    """Base de las excepciones que pueden llevar un dict como `detail`.

    DRF **no** las serializa como FastAPI, y la diferencia rompio clientes en
    silencio. Su manejador por defecto hace:

        data = exc.detail if isinstance(exc.detail, (list, dict))
               else {"detail": exc.detail}

    O sea que un `detail` de tipo str sale como `{"detail": "..."}` pero un dict
    sale **crudo, sin la clave `detail`**. Ademas `APIException` convierte cada
    valor del dict a `ErrorDetail`, que hereda de `str`: `True` se vuelve
    `"True"` y `7` se vuelve `"7"`.

    El frontend lee `e.data.detail` en los dos casos, asi que contra el dict leia
    `undefined`. Efecto real (2026-09-05): al agregar una frontera pendiente de
    Quoia, el aviso de "ya existe una con nombre parecido" -- que es un 409
    reintentable con `?forzar=true` -- llegaba sin su mensaje y sin la bandera
    `duplicado_nombre`, asi que el dialogo de "crear de todos modos" nunca
    aparecia y el usuario solo veia "No se pudo agregar la frontera", sin salida.

    Esta clase guarda el dict original y `manejador_de_excepciones` lo repone
    bajo `detail` con sus tipos intactos, que es el contrato que ya documentaba
    el docstring de `Conflict` y que el frontend siempre espero.
    """

    def __init__(self, detail=None, code=None):
        # Antes de que APIException lo pase por _get_error_details() y aplaste
        # cada valor a str.
        self.cuerpo_dict = detail if isinstance(detail, dict) else None
        super().__init__(detail, code)


def manejador_de_excepciones(exc, context):
    """`EXCEPTION_HANDLER` del proyecto: repone el cuerpo dict bajo `detail`.

    Solo toca las excepciones de este modulo. Las de DRF se dejan como estan --
    en particular `ValidationError`, cuyo dict de errores por campo SI va crudo
    en la raiz, que es el contrato que el frontend ya consume para los 400.
    """
    respuesta = manejador_drf(exc, context)
    if respuesta is None:
        return None
    cuerpo = getattr(exc, "cuerpo_dict", None)
    if cuerpo is not None:
        respuesta.data = {"detail": cuerpo}
    return respuesta


class Conflict(CuerpoPropio):
    """409. `detail` puede ser un dict: sale bajo la clave `detail`, igual que
    lo serializa FastAPI (ver `CuerpoPropio`)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "El recurso ya existe."


class NoProcesable(CuerpoPropio):
    """422. FastAPI devuelve `HTTPException(422, detail=...)` en la validación de
    negocio (un periodo mal formado, un cálculo que no cierra) y no en la del
    request; DRF no tiene equivalente.

    Existe porque `NoProcesable(...)` NO devuelve 422: en DRF el
    `code` es una etiqueta del error, el status lo fija `status_code` de la
    clase — y el de `ValidationError` es 400. Quince endpoints portados
    devolvían 400 donde FastAPI devuelve 422 hasta que se corrigió.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "No se pudo procesar la solicitud."


class ServicioNoDisponible(CuerpoPropio):
    """503. Una dependencia externa (la API de generación de Unergy, Drive) no
    respondió y sin ella el endpoint no puede dar un resultado correcto.

    DRF trae `ServiceUnavailable` solo desde el throttling; se declara acá para
    no confundir "no autentiqué contra Unergy" con "te estoy limitando".
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "El servicio externo no está disponible."
