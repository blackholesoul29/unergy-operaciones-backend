"""Tests del cliente HTTP resiliente (reintentos + circuit breaker)."""
import httpx
import pybreaker
import pytest

from app.services import resilience
from app.services.resilience import ResilientHttpClient


def _make_client(handler, *, attempts=3, fail_max=2, reset_timeout=60):
    """Cliente resiliente apuntando a un MockTransport, sin sleeps reales."""
    client = ResilientHttpClient("evo")
    client.base_url = "http://test.local"
    client.retry_attempts = attempts
    client.backoff_factor = 0  # wait_exponential(0) ⇒ sin esperas
    client.breaker = pybreaker.CircuitBreaker(
        fail_max=fail_max, reset_timeout=reset_timeout, throw_new_error_on_trip=False
    )
    client._transport = httpx.MockTransport(handler)
    return client


@pytest.fixture(autouse=True)
def _inject_transport(monkeypatch):
    """Hace que httpx.Client/AsyncClient usen el MockTransport del cliente bajo test."""
    real_client = httpx.Client
    real_aclient = httpx.AsyncClient
    holder = {}

    def fake_client(*a, **k):
        if "transport" not in k and holder.get("transport"):
            k["transport"] = holder["transport"]
        return real_client(*a, **k)

    def fake_aclient(*a, **k):
        if "transport" not in k and holder.get("transport"):
            k["transport"] = holder["transport"]
        return real_aclient(*a, **k)

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr(httpx, "AsyncClient", fake_aclient)
    return holder


def test_success_first_try(_inject_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    client = _make_client(handler)
    _inject_transport["transport"] = client._transport
    resp = client.request("GET", "/health")
    assert resp.status_code == 200
    assert calls["n"] == 1


def test_retry_then_success(_inject_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)  # transitorio
        return httpx.Response(200, json={"ok": True})

    client = _make_client(handler, attempts=3)
    _inject_transport["transport"] = client._transport
    resp = client.request("GET", "/data")
    assert resp.status_code == 200
    assert calls["n"] == 3  # reintentó dos veces


def test_retry_exhausted_raises(_inject_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)

    client = _make_client(handler, attempts=3, fail_max=10)
    _inject_transport["transport"] = client._transport
    with pytest.raises(httpx.HTTPStatusError):
        client.request("GET", "/data")
    assert calls["n"] == 3  # agotó los 3 intentos


def test_4xx_not_retried_and_returned(_inject_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    client = _make_client(handler, attempts=3)
    _inject_transport["transport"] = client._transport
    resp = client.request("GET", "/missing")
    assert resp.status_code == 404
    assert calls["n"] == 1  # 4xx no se reintenta


def test_circuit_breaker_opens(_inject_transport):
    def handler(request):
        return httpx.Response(500)

    # fail_max=2: tras 2 llamadas fallidas el circuito abre.
    client = _make_client(handler, attempts=1, fail_max=2)
    _inject_transport["transport"] = client._transport

    for _ in range(2):
        with pytest.raises(httpx.HTTPStatusError):
            client.request("GET", "/data")

    # Tercera llamada: circuito abierto ⇒ falla rápido sin tocar la red.
    assert client.breaker.current_state == "open"
    with pytest.raises(pybreaker.CircuitBreakerError):
        client.request("GET", "/data")


def test_circuit_breaker_ignores_4xx(_inject_transport):
    def handler(request):
        return httpx.Response(400)

    client = _make_client(handler, attempts=1, fail_max=2)
    _inject_transport["transport"] = client._transport

    for _ in range(5):
        resp = client.request("GET", "/data")
        assert resp.status_code == 400
    # Los 4xx no cuentan como fallo ⇒ el circuito sigue cerrado.
    assert client.breaker.current_state == "closed"


@pytest.mark.asyncio
async def test_async_retry_then_success(_inject_transport):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(502)
        return httpx.Response(200, json={"ok": True})

    client = _make_client(handler, attempts=3)
    _inject_transport["transport"] = client._transport
    resp = await client.arequest("GET", "/data")
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_get_resilient_client_is_cached():
    a = resilience.get_resilient_client("evo")
    b = resilience.get_resilient_client("evo")
    assert a is b
