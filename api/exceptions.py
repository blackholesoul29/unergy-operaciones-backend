"""Excepciones DRF que faltan para reproducir el contrato actual.

FastAPI permite `HTTPException(409, {...})` con un cuerpo arbitrario, y varios
endpoints lo usan para devolver un aviso de duplicado con los datos del
candidato. DRF no trae un `Conflict`, así que se declara acá una sola vez en vez
de armar `Response(status=409)` a mano en cada vista.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    """409. `detail` puede ser un dict: sale tal cual bajo la clave `detail`,
    igual que lo serializa FastAPI hoy."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "El recurso ya existe."


class NoProcesable(APIException):
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


class ServicioNoDisponible(APIException):
    """503. Una dependencia externa (la API de generación de Unergy, Drive) no
    respondió y sin ella el endpoint no puede dar un resultado correcto.

    DRF trae `ServiceUnavailable` solo desde el throttling; se declara acá para
    no confundir "no autentiqué contra Unergy" con "te estoy limitando".
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "El servicio externo no está disponible."
