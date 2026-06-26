"""Monitoreo de salud de dependencias externas.

Un singleton `health_monitor` corre un `AsyncIOScheduler` que sondea
periódicamente cada API externa crítica (Unergy, SunFactory, Solenium, Quoia,
Gaia, EVO) y mantiene el último estado conocido en memoria. El endpoint
`/api/v1/system-status` expone ese estado agregado.

El sondeo es deliberadamente ligero: hace un GET corto y considera el servicio
*saludable* si responde con un status < 500 (aunque sea 401/404 — significa que
está en pie), e *insalubre* ante errores de red, timeouts o respuestas 5xx. Los
servicios sin URL configurada se marcan como `unconfigured` y no afectan la
salud global.

El sondeo NO pasa por el circuit breaker de `resilience.py`: debe poder probar
el servicio incluso cuando el circuito está abierto.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("health_monitor")

STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"
STATUS_UNKNOWN = "unknown"
STATUS_UNCONFIGURED = "unconfigured"


@dataclass
class ServiceHealth:
    """Estado de salud de un servicio externo."""

    name: str
    status: str = STATUS_UNKNOWN
    last_checked: Optional[str] = None
    latency_ms: Optional[float] = None
    status_code: Optional[int] = None
    detail: str = ""

    @property
    def healthy(self) -> bool:
        return self.status == STATUS_HEALTHY

    def to_dict(self) -> dict:
        d = asdict(self)
        d["healthy"] = self.healthy
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HealthMonitor:
    """Programa y ejecuta los health checks de las dependencias externas."""

    def __init__(self) -> None:
        self._scheduler = None  # AsyncIOScheduler (lazy: requiere event loop)
        self._services: dict[str, ServiceHealth] = {
            name: ServiceHealth(name=name)
            for name in ("unergy", "sunfactory", "solenium", "quoia", "gaia", "evo")
        }

    # ── probing genérico ────────────────────────────────────────────────────────
    async def _probe(self, name: str, url: str | None, headers: dict | None = None) -> ServiceHealth:
        """Sondea `url` y actualiza el estado del servicio `name`."""
        sh = self._services[name]
        if not url:
            sh.status = STATUS_UNCONFIGURED
            sh.last_checked = _now_iso()
            sh.detail = "URL no configurada"
            sh.latency_ms = None
            sh.status_code = None
            return sh

        loop = _monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.HEALTH_CHECK_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=headers or {})
            sh.latency_ms = round((_monotonic() - loop) * 1000, 1)
            sh.status_code = resp.status_code
            sh.last_checked = _now_iso()
            if resp.status_code >= 500:
                sh.status = STATUS_UNHEALTHY
                sh.detail = f"HTTP {resp.status_code}"
            else:
                sh.status = STATUS_HEALTHY
                sh.detail = "ok"
        except httpx.HTTPError as exc:
            sh.latency_ms = round((_monotonic() - loop) * 1000, 1)
            sh.status_code = None
            sh.status = STATUS_UNHEALTHY
            sh.last_checked = _now_iso()
            sh.detail = f"{type(exc).__name__}: {exc}"
            logger.warning("[health] %s insalubre: %s", name, sh.detail)
        return sh

    # ── checks por servicio ──────────────────────────────────────────────────────
    async def check_unergy_api(self) -> ServiceHealth:
        base = (settings.UNERGY_API_BASE_URL or settings.UNERGY_API_URL or "").rstrip("/")
        return await self._probe("unergy", base or None)

    async def check_sunfactory_api(self) -> ServiceHealth:
        base = (settings.SUNFACTORY_API_URL or "").rstrip("/")
        return await self._probe("sunfactory", base or None)

    async def check_solenium_api(self) -> ServiceHealth:
        base = (settings.SOLENIUM_DATA_URL or settings.SOLENIUM_AUTH_URL or "").rstrip("/")
        return await self._probe("solenium", base or None)

    async def check_quoia_api(self) -> ServiceHealth:
        base = (settings.QUOIA_BASE_URL or "").rstrip("/")
        return await self._probe("quoia", base or None)

    async def check_gaia_api(self) -> ServiceHealth:
        base = (settings.GAIA_BASE_URL or "").rstrip("/")
        return await self._probe("gaia", base or None)

    async def check_evo_api(self) -> ServiceHealth:
        base = (settings.EVO_API_URL or "").rstrip("/")
        if not base:
            return await self._probe("evo", None)
        headers = {"X-EVO-Token": settings.EVO_API_TOKEN} if settings.EVO_API_TOKEN else {}
        return await self._probe("evo", f"{base}/health", headers=headers)

    async def check_all(self) -> None:
        """Ejecuta todos los health checks (tolerante a fallos individuales)."""
        checks = [
            self.check_unergy_api,
            self.check_sunfactory_api,
            self.check_solenium_api,
            self.check_quoia_api,
            self.check_gaia_api,
            self.check_evo_api,
        ]
        import asyncio

        results = await asyncio.gather(*[c() for c in checks], return_exceptions=True)
        for fn, res in zip(checks, results):
            if isinstance(res, Exception):
                logger.exception("[health] check %s lanzó excepción", fn.__name__, exc_info=res)

    # ── ciclo de vida ────────────────────────────────────────────────────────────
    def start_monitoring(self) -> None:
        """Arranca el scheduler de health checks. Idempotente."""
        if self._scheduler is not None:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.interval import IntervalTrigger

            scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
            scheduler.add_job(
                self.check_all,
                IntervalTrigger(seconds=settings.HEALTH_CHECK_INTERVAL_SECONDS),
                id="health_check",
                name="External dependencies health check",
                next_run_time=datetime.now(timezone.utc),  # corre uno inmediato
            )
            scheduler.start()
            self._scheduler = scheduler
            logger.info(
                "[health] monitoreo iniciado (intervalo %ss)",
                settings.HEALTH_CHECK_INTERVAL_SECONDS,
            )
        except Exception as exc:
            logger.error("[health] no se pudo iniciar el monitoreo: %s", exc)
            self._scheduler = None

    def stop_monitoring(self) -> None:
        """Detiene el scheduler de health checks. Idempotente."""
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._scheduler = None
            logger.info("[health] monitoreo detenido")

    # ── consulta de estado ────────────────────────────────────────────────────────
    def get_overall_status(self) -> dict:
        """Estado agregado de todas las dependencias externas."""
        services = {name: sh.to_dict() for name, sh in self._services.items()}
        # Global insalubre si algún servicio configurado está marcado insalubre.
        overall_healthy = not any(
            sh.status == STATUS_UNHEALTHY for sh in self._services.values()
        )
        return {
            "overall_healthy": overall_healthy,
            "monitoring_active": self._scheduler is not None,
            "checked_at": _now_iso(),
            "services": services,
        }


def _monotonic() -> float:
    import time

    return time.monotonic()


# Singleton a nivel de módulo.
health_monitor = HealthMonitor()
