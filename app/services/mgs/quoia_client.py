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
        self._http = httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._token}"}

    def _get(self, url: str, params: dict | None = None) -> dict | list | None:
        for attempt in range(1, RETRY_MAX + 1):
            try:
                resp = self._http.get(url, headers=self._headers(), params=params)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("quoia request failed url=%s attempt=%d: %s", url, attempt, exc)
                if attempt == RETRY_MAX:
                    return None
        return None

    def get_all_nodes(self) -> list[dict]:
        data = self._get(f"{self._base_url}/nodes/")
        return data if isinstance(data, list) else []

    def get_meters(self, search: str = "", archived: bool | None = None) -> list[dict]:
        """Fetch all meters (paginated). Returns flat list."""
        all_meters: list[dict] = []
        url = f"{self._base_url}/meter/"
        params: dict = {}
        if search:
            params["search"] = search
        if archived is not None:
            params["archived"] = str(archived).lower()

        while url:
            data = self._get(url, params=params if not all_meters else None)
            if not data or not isinstance(data, dict):
                break
            all_meters.extend(data.get("results", []))
            url = data.get("next")
        return all_meters

    def get_typical_curves(self, node_id: int | None = None) -> list[dict]:
        """Fetch typical consumption/generation curves."""
        url = f"{self._base_url}/measurement/typical_curve/"
        params = {"node": node_id} if node_id else None
        all_curves: list[dict] = []

        while url:
            data = self._get(url, params=params if not all_curves else None)
            if not data or not isinstance(data, dict):
                break
            all_curves.extend(data.get("results", []))
            url = data.get("next")
        return all_curves
