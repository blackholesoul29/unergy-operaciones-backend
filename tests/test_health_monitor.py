"""Tests del monitor de salud de dependencias externas."""
import httpx
import pytest

from app.services.health_monitor import (
    STATUS_HEALTHY,
    STATUS_UNCONFIGURED,
    STATUS_UNHEALTHY,
    HealthMonitor,
)


@pytest.fixture
def monitor():
    return HealthMonitor()


def _patch_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_aclient = httpx.AsyncClient

    def fake_aclient(*a, **k):
        k.setdefault("transport", transport)
        return real_aclient(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", fake_aclient)


@pytest.mark.asyncio
async def test_probe_healthy(monitor, monkeypatch):
    _patch_transport(monkeypatch, lambda req: httpx.Response(200))
    sh = await monitor._probe("evo", "http://test.local/health")
    assert sh.status == STATUS_HEALTHY
    assert sh.healthy is True
    assert sh.status_code == 200
    assert sh.last_checked is not None


@pytest.mark.asyncio
async def test_probe_4xx_is_healthy(monitor, monkeypatch):
    # 401/404 ⇒ el servicio está en pie, sólo requiere auth ⇒ healthy.
    _patch_transport(monkeypatch, lambda req: httpx.Response(401))
    sh = await monitor._probe("quoia", "http://test.local")
    assert sh.status == STATUS_HEALTHY
    assert sh.status_code == 401


@pytest.mark.asyncio
async def test_probe_5xx_is_unhealthy(monitor, monkeypatch):
    _patch_transport(monkeypatch, lambda req: httpx.Response(500))
    sh = await monitor._probe("gaia", "http://test.local")
    assert sh.status == STATUS_UNHEALTHY
    assert sh.healthy is False


@pytest.mark.asyncio
async def test_probe_network_error_is_unhealthy(monitor, monkeypatch):
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    _patch_transport(monkeypatch, handler)
    sh = await monitor._probe("solenium", "http://test.local")
    assert sh.status == STATUS_UNHEALTHY
    assert "ConnectError" in sh.detail


@pytest.mark.asyncio
async def test_probe_unconfigured(monitor):
    sh = await monitor._probe("unergy", None)
    assert sh.status == STATUS_UNCONFIGURED
    assert sh.healthy is False


@pytest.mark.asyncio
async def test_overall_status_degrades_on_unhealthy(monitor, monkeypatch):
    # Todos responden 500 ⇒ overall_healthy = False.
    _patch_transport(monkeypatch, lambda req: httpx.Response(503))
    await monitor.check_all()
    status = monitor.get_overall_status()
    assert status["overall_healthy"] is False
    assert set(status["services"]) == {
        "unergy", "sunfactory", "solenium", "quoia", "gaia", "evo",
    }


def test_overall_status_initial_is_healthy(monitor):
    # Sin checks aún: ningún servicio está marcado insalubre.
    status = monitor.get_overall_status()
    assert status["overall_healthy"] is True
    assert status["monitoring_active"] is False


def test_start_and_stop_monitoring(monitor):
    import asyncio

    async def run():
        monitor.start_monitoring()
        active = monitor.get_overall_status()["monitoring_active"]
        monitor.stop_monitoring()
        stopped = monitor.get_overall_status()["monitoring_active"]
        return active, stopped

    # AsyncIOScheduler requiere un event loop corriendo.
    active, stopped = asyncio.run(run())
    assert active is True
    assert stopped is False
