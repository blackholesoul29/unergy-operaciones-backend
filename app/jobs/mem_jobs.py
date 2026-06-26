"""
Jobs programados del módulo MEM.

Descargan los archivos diarios de XM (generación ASIC, precios de bolsa) y los
alimentan al `MEMIngestionService`. La descarga real depende de la fuente de XM
(HTTP/FTP); las URLs se leen de settings (`MEM_ASIC_URL`, `MEM_PRECIOS_URL`) y,
si no están configuradas, el job sólo registra que no hay fuente y termina sin
error — así el scheduler arranca aunque la integración aún no esté lista.
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.mem_ingestion_service import MEMIngestionService

logger = logging.getLogger(__name__)


def _download(url: str) -> bytes | None:
    """Descarga el contenido de una URL (HTTP/HTTPS)."""
    try:
        import httpx
        resp = httpx.get(url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as e:  # noqa: BLE001
        logger.warning("[mem_jobs] descarga falló (%s): %s", url, e)
        return None


def fetch_daily_asic_data() -> dict | None:
    """Descarga y persiste la generación ASIC del día."""
    url = getattr(settings, "MEM_ASIC_URL", "") or ""
    if not url:
        logger.info("[mem_jobs] MEM_ASIC_URL no configurada — se omite fetch ASIC")
        return None
    content = _download(url)
    if not content:
        return None
    db = SessionLocal()
    try:
        summary = MEMIngestionService(db).ingest_asic_data(content, filename=url)
        logger.info("[mem_jobs] ASIC ingerido: %s", summary)
        return summary
    finally:
        db.close()


def fetch_daily_prices() -> dict | None:
    """Descarga y persiste los precios de bolsa del día."""
    url = getattr(settings, "MEM_PRECIOS_URL", "") or ""
    if not url:
        logger.info("[mem_jobs] MEM_PRECIOS_URL no configurada — se omite fetch precios")
        return None
    content = _download(url)
    if not content:
        return None
    db = SessionLocal()
    try:
        summary = MEMIngestionService(db).ingest_precio_bolsa(content, filename=url)
        logger.info("[mem_jobs] Precios ingeridos: %s", summary)
        return summary
    finally:
        db.close()
