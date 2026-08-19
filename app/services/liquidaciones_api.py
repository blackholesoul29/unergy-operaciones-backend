"""Cliente de la API de Liquidaciones de Unergy (api.unergy.io).

Los datos maestros que usa el ciclo de liquidaciones -- códigos SIC/FRT,
``ac_power`` y los flags de generador/comercializador -- viven en esa API y no
en esta base de datos. Este módulo es el único punto que habla HTTP con ella.

Particularidades de la API, verificadas contra producción:

* La autenticación es ``POST /api/accounts/<account_id>/`` con login+password y
  devuelve un JWT de acceso. Un 401 posterior significa token vencido: hay que
  renovarlo y reintentar, no es "sin datos".
* Rechaza clientes sin un ``User-Agent`` conocido, así que se envía uno fijo.
* ``/api/admin/*`` exige ``is_staff`` y ``/api/liquidaciones/*`` pertenecer al
  grupo ``admin``; la cuenta de servicio debe cumplir ambos.
"""
import logging
import threading
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("liquidaciones_api")

# Rutas de la API externa (sin hardcodearlas en los endpoints que las consumen).
PATH_LOGIN = "/api/accounts/{account_id}/"
PATH_PROYECTOS = "/api/admin/project/"
PATH_PROYECTO = "/api/admin/project/{topico}/"

# Campos de configuración del proyecto que expone esta integración (§3.1 de la
# guía). Se listan explícitamente porque el recurso trae ~65 campos y solo estos
# intervienen en el ciclo de liquidaciones.
CAMPOS_PROYECTO = (
    "sic_gen",
    "sic_con",
    "frt_gen",
    "frt_con",
    "ac_power",
    "from_generator",
    "from_commercializer",
)

_TIMEOUT = httpx.Timeout(15.0, read=60.0)
_USER_AGENT = "PostmanRuntime/7.50.0"

_token: str | None = None
_token_lock = threading.Lock()


class LiquidacionesAPIError(RuntimeError):
    """Falla al comunicarse con la API de Liquidaciones."""


def _credenciales() -> tuple[str, str]:
    """Credenciales de la cuenta de servicio, con respaldo en las de UNERGY_*."""
    login = settings.LIQUIDACIONES_LOGIN or settings.UNERGY_LOGIN
    password = settings.LIQUIDACIONES_PASSWORD or settings.UNERGY_PASSWORD
    if not (login and password and settings.UNERGY_ACCOUNT_ID):
        raise LiquidacionesAPIError(
            "Faltan credenciales: configura LIQUIDACIONES_LOGIN, "
            "LIQUIDACIONES_PASSWORD y UNERGY_ACCOUNT_ID."
        )
    return login, password


def _url(path: str) -> str:
    return f"{settings.UNERGY_API_URL.rstrip('/')}{path}"


def _login() -> str:
    """Pide un token nuevo y lo deja cacheado en el módulo."""
    global _token
    login, password = _credenciales()
    url = _url(PATH_LOGIN.format(account_id=settings.UNERGY_ACCOUNT_ID))
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                url,
                json={"login": login, "password": password},
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            token = resp.json()["access"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.exception("No se pudo autenticar contra la API de Liquidaciones")
        raise LiquidacionesAPIError("No se pudo autenticar contra la API de Liquidaciones") from exc

    _token = token
    return token


def _request(method: str, path: str, **kwargs: Any) -> Any:
    """Ejecuta la llamada renovando el token una sola vez si expiró (401)."""
    global _token

    with _token_lock:
        token = _token or _login()

    def _enviar(bearer: str) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT) as client:
            return client.request(
                method,
                _url(path),
                headers={"Authorization": f"Bearer {bearer}", "User-Agent": _USER_AGENT},
                **kwargs,
            )

    try:
        resp = _enviar(token)
        if resp.status_code == 401:
            with _token_lock:
                token = _login()
            resp = _enviar(token)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "API de Liquidaciones respondió %s en %s", exc.response.status_code, path
        )
        raise LiquidacionesAPIError(
            f"La API de Liquidaciones respondió {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        logger.exception("Error de red hablando con la API de Liquidaciones")
        raise LiquidacionesAPIError("No se pudo contactar la API de Liquidaciones") from exc

    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise LiquidacionesAPIError("La API de Liquidaciones devolvió una respuesta no JSON") from exc


def _proyectar(proyecto: dict[str, Any]) -> dict[str, Any]:
    """Deja solo el identificador y los campos del ciclo de liquidaciones."""
    datos = {campo: proyecto.get(campo) for campo in CAMPOS_PROYECTO}
    datos["nombre_topico"] = proyecto.get("nombre_topico")
    datos["nombre_proyecto"] = proyecto.get("nombre_proyecto")
    return datos


def listar_proyectos() -> list[dict[str, Any]]:
    """Configuración de liquidaciones de todos los proyectos, en una sola llamada."""
    data = _request("GET", PATH_PROYECTOS)
    if not isinstance(data, list):
        raise LiquidacionesAPIError("Se esperaba una lista de proyectos")
    return [_proyectar(p) for p in data]


def actualizar_proyecto(topico: str, cambios: dict[str, Any]) -> dict[str, Any]:
    """Actualiza los campos de §3.1 de un proyecto, identificado por su tópico."""
    permitidos = {k: v for k, v in cambios.items() if k in CAMPOS_PROYECTO}
    if not permitidos:
        raise LiquidacionesAPIError("No hay campos válidos para actualizar")
    data = _request("PATCH", PATH_PROYECTO.format(topico=topico), json=permitidos)
    return _proyectar(data) if isinstance(data, dict) else {}
