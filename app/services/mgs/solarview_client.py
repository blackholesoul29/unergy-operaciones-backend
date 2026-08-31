"""Sync HTTP client for SolarView API (reemplazo de Solenium, Fase 1: solo
los métodos que usa Reporte de Energía -- ver plan de migración).

Auth: token estático por header, sin login/refresh (a diferencia de
SoleniumClient, que usa JWT con /token/ + /token/refresh/).
"""
from __future__ import annotations

import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger("mgs.solarview")

RETRY_MAX = 2
TIMEOUT = 30.0
BACKOFF_SECONDS = 2.0


class SolarViewClient:
    def __init__(self):
        self._base_url = settings.SOLARVIEW_BASE_URL.rstrip("/")
        self._token = settings.SOLARVIEW_TOKEN
        self._http = httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._token}"}

    def _get(self, url: str, params: dict | None = None) -> dict | list | None:
        for attempt in range(1, RETRY_MAX + 1):
            if not self._token:
                return None
            try:
                resp = self._http.get(url, headers=self._headers(), params=params)
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429, 503) and attempt < RETRY_MAX:
                    # Reintentar de inmediato ante rate limiting no sirve de
                    # nada -- con ~37 fronteras y hasta 2 llamadas cada una en
                    # la corrida diaria, un 429 sin espera probablemente
                    # vuelva a chocar con el mismo límite. Se respeta
                    # Retry-After si la API lo manda, si no una pausa fija.
                    espera = BACKOFF_SECONDS
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            espera = max(espera, float(retry_after))
                        except ValueError:
                            pass
                    time.sleep(espera)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("solarview request failed url=%s attempt=%d: %s", url, attempt, exc)
                if attempt == RETRY_MAX:
                    return None
        return None

    def get_availability(self) -> dict[int, dict]:
        """Disponibilidad de toda la flota en una sola llamada, agrupada por
        categoria (`high`/`medium`/`disconnect`) -- GET /solarview/kpis/availability/.

        Mismo shape de salida que SoleniumClient.get_availability()
        ({project_id: {name, availability, category}}) a proposito: permite
        que un llamador (ej. alarmas de desconexion) trate ambas fuentes
        igual sin ramas por proveedor."""
        url = f"{self._base_url}/solarview/kpis/availability/"
        data = self._get(url)
        if not isinstance(data, dict):
            return {}
        result: dict[int, dict] = {}
        for cat in (data.get("results") or {}).get("categories", []):
            cat_id = cat.get("id", "unknown")
            for item in cat.get("items", []):
                pid = item.get("project")
                if pid is not None:
                    result[pid] = {
                        "name": (item.get("name") or "").strip(),
                        "availability": item.get("availability"),
                        "category": cat_id,
                    }
        return result

    def get_company_projects(self) -> list[dict]:
        """Proyectos en operación disponibles para este cliente -- cada item
        trae {id, name, lon, lat, plant_code, is_minifarm}. Es el listado que
        se usa para emparejar por nombre y asignar project_id_solarview (ver
        app/services/proyectos_backfill_solarview.py), igual que
        SoleniumClient.get_projects() para project_id_solenium -- los dos
        esquemas de id NO coinciden entre sí, no se puede derivar uno del otro.
        """
        url = f"{self._base_url}/solarview/config/company-projects/"
        data = self._get(url)
        if not isinstance(data, dict):
            return []
        results = data.get("results")
        return results if isinstance(results, list) else []

    def get_generation(self, project_id: int, start_date: str, end_date: str) -> dict | None:
        url = f"{self._base_url}/solarview/measurements/generation/"
        return self._get(url, params={
            "project_id": project_id,
            "start_date": start_date,
            "end_date": end_date,
        })

    def get_power(self, project_id: int, date_from: str = "", date_to: str = "") -> dict | None:
        url = f"{self._base_url}/solarview/measurements/power/"
        params: dict = {"project_id": project_id, "power": "active_power", "total_power": 1}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return self._get(url, params=params)

    def get_relay_historical(self, project_id: int, start_date: str, end_date: str,
                              variables: str = "kw") -> dict | None:
        """Histórico del reconectador de un proyecto en un rango de fechas.

        start_date / end_date: "YYYY-MM-DD HH:MM:SS" (verificado en vivo --
        pese a lo que dice la documentación de SolarView sobre ISO 8601 con
        offset, el endpoint real sigue esperando este formato viejo y
        responde 400 con el otro).
        """
        url = f"{self._base_url}/solarview/config/recloser/historical/"
        return self._get(url, params={
            "recloser": project_id,
            "start_date": start_date,
            "end_date": end_date,
            "vars": variables,
        })
