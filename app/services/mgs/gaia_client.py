"""Sync HTTP client for Gaia (Quoia CGM) API — JWT auth.

Provides access to:
  - /api/cgm/v1/border/          → grid connection borders
  - /api/node/{id}/measurements/ → electrical node measurements (V, I, P, Q, PF, energy)

Authentication uses username/password JWT (Bearer token), different from the
legacy QuoiaClient which uses a static API Token.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import settings

logger = logging.getLogger("mgs.gaia")

TIMEOUT = 30.0
TOKEN_REFRESH_SEC = 4 * 60   # refresh access token every 4 min (they typically expire in 5)

# ── Hardcoded node map: frt_code → Gaia node_id (Principal meter) ─────────────
# Source: nodos.json from the Plataforma Central de Monitoreo.
# Key = frontera SIC code, Value = numeric Gaia node ID or None if not registered.
FRONTERA_NODE_MAP: dict[str, int | None] = {
    "frt55044": 603,    # MINIGRANJA SOLAR BARAYA
    "frt55090": 609,    # MINIGRANJA SOLAR GANDALF
    "frt55093": 606,    # MINIGRANJA SOLAR CAÑAHUATE
    "frt58839": 845,    # Minigranja 005 - La Paz Vallenata
    "frt60629": 848,    # Minigranja Solar 0006 - Perijá
    "frt63879": 1022,   # Minigranja 0009 La Paz Verso
    "frt65205": 1283,   # Minigranja 0018 - La Paz Leyenda
    "frt66597": 1459,   # Minigranja 0017 - La Paz Esmeralda
    "frt67475": 1481,   # MGS 0015 - El Son
    "frt67496": 1489,   # MGS 0019 - El Merengue
    "frt68269": 1514,   # MGS 0016 - La Puya
    "frt73414": 1590,   # MGS 0021 - Ibirico
    "frt74080": 1584,   # MGS 0022 - La Cumbia
    "frt76578": 1656,   # MGS 0024 - San Diego Sur
    "frt76581": None,   # MGS 0020 - El Mapalé (sin nodo registrado)
    "frt76586": None,   # MGS 0023 - El Joropo (sin nodo registrado)
    "frt82546": 1664,   # MGS 0027 - Valencia Oriente 2
    "frt82576": None,   # MGS 0025 - El Copey Occidente (sin nodo registrado)
    "frt82846": None,   # Sol&Cielo 7 Los Bongos (sin nodo)
    "frt84587": 1712,   # GD San Pelayo
    "frt86234": 1660,   # MGS 0026 - Valencia Oriente
    "frt87017": 1722,   # MGS 0040 - La Cacica
    "frt87018": 1724,   # MGS 0041 - Las Piloneras
    "frt87336": 1716,   # La Catedral
    "frt89202": 1719,   # Sol&Cielo 9 - Ciénaga Generación
    "frt92219": 1739,   # MGS 0075 - Chiriguaná Norte 2
    "frt92221": 1730,   # MGS 0077 - Chiriguaná Norte 4
}

# minigranja number → frontera code (for numbered projects)
_NUM_TO_FRT: dict[int, str] = {
    5:  "frt58839",
    6:  "frt60629",
    9:  "frt63879",
    15: "frt67475",
    16: "frt68269",
    17: "frt66597",
    18: "frt65205",
    19: "frt67496",
    20: "frt76581",
    21: "frt73414",
    22: "frt74080",
    23: "frt76586",
    24: "frt76578",
    25: "frt82576",
    26: "frt86234",
    27: "frt82546",
    40: "frt87017",
    41: "frt87018",
    75: "frt92219",
    77: "frt92221",
}

# keyword → frontera code (for early minigranjas without numbers)
_KW_TO_FRT: dict[str, str] = {
    "baraya":    "frt55044",
    "gandalf":   "frt55090",
    "canahuate": "frt55093",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


def _mgs_number(name: str) -> int | None:
    m = re.search(r"(?:minigranja|mgs|mgr)\s+0*(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def find_gaia_node_id(*names: str) -> int | None:
    """Find the Gaia node_id for a project given any combination of its names.

    Tries minigranja number matching first, then keyword matching for
    early minigranjas that don't have a number.
    Returns None if no mapping is found.
    """
    for name in names:
        if not name:
            continue
        # Number match
        num = _mgs_number(name)
        if num is not None:
            frt = _NUM_TO_FRT.get(num)
            if frt:
                node_id = FRONTERA_NODE_MAP.get(frt)
                if node_id is not None:
                    return node_id
        # Keyword match
        n = _norm(name)
        for kw, frt in _KW_TO_FRT.items():
            if kw in n:
                node_id = FRONTERA_NODE_MAP.get(frt)
                if node_id is not None:
                    return node_id
    return None


def _col_today() -> str:
    """Current date in Colombia time (UTC-5), formatted YYYY-MM-DD."""
    col = datetime.now(timezone.utc) - timedelta(hours=5)
    return col.strftime("%Y-%m-%d")


class GaiaClient:
    """JWT-authenticated client for the Gaia CGM API.

    Handles token refresh automatically. Thread-safe for concurrent reads
    within a single request (multiple measurement vars fetched in parallel).
    """

    def __init__(self):
        self._base = settings.GAIA_BASE_URL.rstrip("/")
        self._username = settings.GAIA_USER
        self._password = settings.GAIA_PASS
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_time: float = 0
        self._http = httpx.Client(timeout=TIMEOUT)

    @property
    def enabled(self) -> bool:
        return bool(self._username and self._password)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        try:
            resp = self._http.post(f"{self._base}/api/auth/token/", json={
                "username": self._username,
                "password": self._password,
            })
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access"]
            self._refresh_token = data["refresh"]
            self._token_time = time.time()
        except Exception as exc:
            logger.error("gaia auth failed: %s", exc)
            self._access_token = None
            self._refresh_token = None

    def _try_refresh(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            resp = self._http.post(f"{self._base}/api/auth/token/refresh/",
                                   json={"refresh": self._refresh_token})
            resp.raise_for_status()
            self._access_token = resp.json()["access"]
            self._token_time = time.time()
            return True
        except Exception:
            return False

    def _ensure_token(self) -> None:
        if not self._access_token:
            self._authenticate()
            return
        if time.time() - self._token_time > TOKEN_REFRESH_SEC:
            if not self._try_refresh():
                self._authenticate()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, url: str, params: dict | None = None) -> dict | list | None:
        self._ensure_token()
        if not self._access_token:
            return None
        try:
            resp = self._http.get(url, headers=self._headers(), params=params)
            if resp.status_code == 401:
                # One retry after re-auth
                self._access_token = None
                self._authenticate()
                if not self._access_token:
                    return None
                resp = self._http.get(url, headers=self._headers(), params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("gaia request failed url=%s: %s", url, exc)
            return None

    # ── Public methods ─────────────────────────────────────────────────────────

    def get_node_measurements(self, node_id: int, date_str: str, var_name: str) -> list[dict]:
        """Fetch measurement rows for one variable from a node for a given date.

        var_name: one of  v, c, ap, rp, pf, eae, iae, ere, ire
        Returns list of dicts, each containing a 'time' key and per-phase fields.
        """
        url = f"{self._base}/api/node/{node_id}/measurements/"
        params = {
            "init_date": f"{date_str}T00:00:00-05:00",
            "end_date":  f"{date_str}T23:59:59-05:00",
            "vars":      var_name,
        }
        data = self._get(url, params=params)
        return data if isinstance(data, list) else []

    def get_node_electrical_snapshot(self, node_id: int) -> dict | None:
        """Comprehensive electrical snapshot for a node (today).

        Fetches all 8 variable families in parallel and returns:
          - Instantaneous: voltage per phase (vp1/2/3), current (cp1/2/3),
            active power (ap1/2/3 + ap_total), reactive power (rp1/2/3 + rp_total),
            power factor (pf1/2/3 + pf_avg)
          - Cumulative today: energy exported (eae_wh), imported (iae_wh),
            reactive exported (ere_wh), all with per-phase breakdown
          - last_time: ISO timestamp of the most recent datapoint
        Returns None if no data is available.
        """
        date_str = _col_today()
        VARS = ["v", "c", "ap", "rp", "pf", "eae", "iae", "ere"]

        results: dict[str, list] = {}
        # Each variable requires its own request (API restriction)
        with ThreadPoolExecutor(max_workers=len(VARS)) as ex:
            futs = {v: ex.submit(self.get_node_measurements, node_id, date_str, v)
                    for v in VARS}
            for var, fut in futs.items():
                try:
                    results[var] = fut.result() or []
                except Exception:
                    results[var] = []

        def _last(lst: list) -> dict:
            return lst[-1] if lst else {}

        def _sum(*fields: str, data: list) -> float | None:
            total: float | None = None
            for row in data:
                for f in fields:
                    v = row.get(f)
                    if v is not None:
                        total = (total or 0.0) + float(v)
            return total

        lv  = _last(results["v"])
        lc  = _last(results["c"])
        lap = _last(results["ap"])
        lrp = _last(results["rp"])
        lpf = _last(results["pf"])
        eae = results["eae"]
        iae = results["iae"]
        ere = results["ere"]

        if not lv and not lc and not lap:
            return None

        # Most recent timestamp across all vars
        all_times = [r[-1].get("time") for r in results.values() if r]
        last_time = max((t for t in all_times if t), default=None)

        return {
            # Voltage per phase [V]
            "vp1": lv.get("vp1"), "vp2": lv.get("vp2"), "vp3": lv.get("vp3"),
            # Current per phase [A]
            "cp1": lc.get("cp1"), "cp2": lc.get("cp2"), "cp3": lc.get("cp3"),
            # Active power [W] — per phase and aggregate
            "ap1": lap.get("ap1"), "ap2": lap.get("ap2"), "ap3": lap.get("ap3"),
            "ap_total": lap.get("ap"),
            # Reactive power [VAR]
            "rp1": lrp.get("rp1"), "rp2": lrp.get("rp2"), "rp3": lrp.get("rp3"),
            "rp_total": lrp.get("rp"),
            # Power factor (dimensionless, usually -1..1 or 0..1)
            "pf1": lpf.get("pf1"), "pf2": lpf.get("pf2"), "pf3": lpf.get("pf3"),
            "pf_avg": lpf.get("pf"),
            # Cumulative energy today [Wh]
            "eae_wh":  _sum("eae",  data=eae),
            "eae1_wh": _sum("eae1", data=eae),
            "eae2_wh": _sum("eae2", data=eae),
            "eae3_wh": _sum("eae3", data=eae),
            "iae_wh":  _sum("iae",  data=iae),
            "iae1_wh": _sum("iae1", data=iae),
            "iae2_wh": _sum("iae2", data=iae),
            "iae3_wh": _sum("iae3", data=iae),
            "ere_wh":  _sum("ere",  data=ere),
            "ere1_wh": _sum("ere1", data=ere),
            "ere2_wh": _sum("ere2", data=ere),
            "ere3_wh": _sum("ere3", data=ere),
            "last_time": last_time,
        }
