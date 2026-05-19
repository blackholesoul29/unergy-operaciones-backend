"""Sync HTTP client for Quoia CGM API (fronteras / medidores)."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("mgs.quoia")

RETRY_MAX = 2
TIMEOUT = 30.0


class QuoiaClient:
    def __init__(self):
        self._base_url = settings.QUOIA_BASE_URL.rstrip("/")
        self._token = settings.QUOIA_API_TOKEN
        self._http = httpx.Client(timeout=TIMEOUT)

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._token}"}

    def get_all_nodes(self) -> list[dict]:
        url = f"{self._base_url}/nodes/"
        for attempt in range(1, RETRY_MAX + 1):
            try:
                resp = self._http.get(url, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("quoia request failed attempt=%d: %s", attempt, exc)
                if attempt == RETRY_MAX:
                    logger.error("quoia request exhausted: %s", url)
                    return []
        return []
