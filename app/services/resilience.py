"""Resiliencia centralizada para llamadas a APIs externas.

Combina tres patrones sobre `httpx`:

* **Reintentos** con backoff exponencial (`tenacity`) ante errores transitorios
  (timeouts, errores de conexión, respuestas 5xx).
* **Circuit breaker** por servicio (`pybreaker`): tras N fallos consecutivos el
  circuito se abre y las llamadas fallan rápido (`CircuitBreakerError`) durante
  un periodo de reposo, evitando fallos en cascada.
* **Timeouts** uniformes tomados de la configuración.

Uso típico (síncrono, como en los endpoints actuales)::

    from app.services.resilience import get_resilient_client
    import pybreaker, httpx

    client = get_resilient_client("evo")
    try:
        resp = client.request("GET", "/health", headers={...})
        resp.raise_for_status()
        data = resp.json()
    except pybreaker.CircuitBreakerError:
        raise HTTPException(503, "EVO no disponible (circuito abierto)")
    except httpx.HTTPError:
        raise HTTPException(503, "EVO no disponible")

Las respuestas 4xx se devuelven al llamador sin reintentar ni contar como fallo
del breaker (son errores del cliente, no de disponibilidad). Sólo los 5xx y los
errores de red activan reintentos y el circuit breaker.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import pybreaker
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

logger = logging.getLogger("resilience")


# ── Configuración por servicio ─────────────────────────────────────────────────
def _base_url(service: str) -> str:
    """Resuelve la base URL de un servicio desde settings (puede estar vacía)."""
    mapping = {
        "unergy": settings.UNERGY_API_BASE_URL or settings.UNERGY_API_URL,
        "sunfactory": settings.SUNFACTORY_API_URL,
        "solenium": settings.SOLENIUM_DATA_URL,
        "quoia": settings.QUOIA_BASE_URL,
        "gaia": settings.GAIA_BASE_URL,
        "evo": settings.EVO_API_URL,
    }
    return (mapping.get(service) or "").rstrip("/")


def _retry_attempts(service: str) -> int:
    overrides = {
        "evo": settings.EVO_API_RETRY_ATTEMPTS,
        "unergy": settings.UNERGY_API_RETRY_ATTEMPTS,
    }
    return overrides.get(service) or settings.DEFAULT_API_RETRY_ATTEMPTS


def _breaker_failure_threshold(service: str) -> int:
    overrides = {
        "evo": settings.EVO_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        "unergy": settings.UNERGY_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    }
    return overrides.get(service) or settings.DEFAULT_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD


def _breaker_reset_timeout(service: str) -> int:
    overrides = {
        "evo": settings.EVO_API_CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS,
        "unergy": settings.UNERGY_API_CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS,
    }
    return overrides.get(service) or settings.DEFAULT_API_CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS


# Servicios externos críticos con circuit breaker propio.
SERVICES = ["unergy", "sunfactory", "solenium", "quoia", "gaia", "evo"]


class _BreakerLogger(pybreaker.CircuitBreakerListener):
    """Registra los cambios de estado del circuito en el log."""

    def state_change(self, cb, old_state, new_state):  # noqa: D401
        logger.warning(
            "[circuit-breaker] %s: %s -> %s",
            cb.name, getattr(old_state, "name", old_state), getattr(new_state, "name", new_state),
        )


def _build_breaker(service: str) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=_breaker_failure_threshold(service),
        reset_timeout=_breaker_reset_timeout(service),
        name=service,
        listeners=[_BreakerLogger()],
        # La llamada que dispara la apertura propaga el error original (5xx/red);
        # sólo las llamadas posteriores fallan rápido con CircuitBreakerError.
        throw_new_error_on_trip=False,
    )


async def _breaker_call_async(breaker: pybreaker.CircuitBreaker, coro_func):
    """Equivalente asíncrono de `breaker.call`.

    `pybreaker.call_async` depende de Tornado (`gen`), que no usamos; replicamos
    aquí la lógica de `CircuitBreakerState.call`: comprobar el estado (fail-fast
    si está abierto) y registrar éxito/fallo, ejecutando el await fuera del lock.
    """
    with breaker._lock:
        state = breaker.state
        state.before_call(coro_func)  # lanza CircuitBreakerError si está abierto
        for listener in breaker.listeners:
            listener.before_call(breaker, coro_func)
    try:
        ret = await coro_func()
    except BaseException as exc:  # noqa: BLE001 — se re-lanza dentro de _handle_error
        with breaker._lock:
            breaker.state._handle_error(exc)  # reraise=True por defecto
        raise
    else:
        with breaker._lock:
            breaker.state._handle_success()
        return ret


# Una instancia de CircuitBreaker por servicio, compartida por todas las llamadas.
breakers: dict[str, pybreaker.CircuitBreaker] = {s: _build_breaker(s) for s in SERVICES}

# Atajos nombrados (referenciados directamente en algunos módulos / tests).
unergy_breaker = breakers["unergy"]
sunfactory_breaker = breakers["sunfactory"]
solenium_breaker = breakers["solenium"]
quoia_breaker = breakers["quoia"]
gaia_breaker = breakers["gaia"]
evo_breaker = breakers["evo"]


# ── Detección de errores transitorios ───────────────────────────────────────────
def _is_transient(exc: BaseException) -> bool:
    """¿El error amerita reintento? Timeouts, errores de red y respuestas 5xx."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class ResilientHttpClient:
    """Cliente HTTP con reintentos + circuit breaker para un servicio dado.

    Expone una API síncrona (`request`/`get`/`post`) y otra asíncrona
    (`arequest`/`aget`/`apost`). Devuelve el `httpx.Response`; el llamador decide
    qué hacer con los 4xx (no se reintentan ni abren el circuito).
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        self.base_url = _base_url(service_name)
        self.breaker = breakers.get(service_name) or _build_breaker(service_name)
        self.retry_attempts = _retry_attempts(service_name)
        self.backoff_factor = settings.DEFAULT_API_RETRY_BACKOFF_FACTOR
        self.timeout = settings.EXTERNAL_API_TIMEOUT_SECONDS

    # -- helpers internos --------------------------------------------------------
    def _full_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not self.base_url:
            raise RuntimeError(f"Base URL no configurada para el servicio '{self.service_name}'")
        return f"{self.base_url}/{path.lstrip('/')}"

    def _raise_if_server_error(self, resp: httpx.Response) -> httpx.Response:
        # Sólo 5xx se considera fallo de disponibilidad (transitorio).
        if resp.is_server_error:
            resp.raise_for_status()
        return resp

    # -- API síncrona ------------------------------------------------------------
    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._full_url(path)
        kwargs.setdefault("timeout", self.timeout)

        def _do() -> httpx.Response:
            with httpx.Client() as client:
                resp = client.request(method, url, **kwargs)
            return self._raise_if_server_error(resp)

        retrying = Retrying(
            stop=stop_after_attempt(self.retry_attempts),
            wait=wait_exponential(multiplier=self.backoff_factor),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        return self.breaker.call(lambda: retrying(_do))

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    # -- API asíncrona -----------------------------------------------------------
    async def arequest(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = self._full_url(path)
        kwargs.setdefault("timeout", self.timeout)

        async def _do() -> httpx.Response:
            async with httpx.AsyncClient() as client:
                resp = await client.request(method, url, **kwargs)
            return self._raise_if_server_error(resp)

        async def _retrying() -> httpx.Response:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retry_attempts),
                wait=wait_exponential(multiplier=self.backoff_factor),
                retry=retry_if_exception(_is_transient),
                reraise=True,
            ):
                with attempt:
                    return await _do()

        return await _breaker_call_async(self.breaker, _retrying)

    async def aget(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.arequest("GET", path, **kwargs)

    async def apost(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.arequest("POST", path, **kwargs)


# Caché de clientes por servicio (son baratos pero comparten el breaker singleton).
_clients: dict[str, ResilientHttpClient] = {}


def get_resilient_client(service_name: str) -> ResilientHttpClient:
    """Devuelve (creando si hace falta) el cliente resiliente de un servicio."""
    client = _clients.get(service_name)
    if client is None:
        client = ResilientHttpClient(service_name)
        _clients[service_name] = client
    return client
