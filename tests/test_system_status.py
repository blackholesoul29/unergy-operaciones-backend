"""Tests de integración del endpoint /system-status."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import system_status
from app.services.health_monitor import STATUS_UNHEALTHY


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(system_status.router)
    return TestClient(app)


def test_system_status_structure(client):
    resp = client.get("/system-status")
    assert resp.status_code == 200
    body = resp.json()
    assert "overall_healthy" in body
    assert isinstance(body["overall_healthy"], bool)
    assert "services" in body
    for name in ("unergy", "sunfactory", "solenium", "quoia", "gaia", "evo"):
        assert name in body["services"]
        assert "status" in body["services"][name]
        assert "healthy" in body["services"][name]


def test_system_status_reflects_degradation(client, monkeypatch):
    # Forzamos que todas las dependencias respondan 500 y refrescamos.
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    real_aclient = httpx.AsyncClient

    def fake_aclient(*a, **k):
        k.setdefault("transport", transport)
        return real_aclient(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", fake_aclient)

    resp = client.post("/system-status/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_healthy"] is False
    # Al menos un servicio configurado quedó insalubre.
    assert any(s["status"] == STATUS_UNHEALTHY for s in body["services"].values())
