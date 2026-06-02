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

# Nodos cuyo firmware reporta eaepd en Wh en lugar de kWh.
# Para todos los demás se asume kWh directamente.
_EAE_WH_NODES: frozenset[int] = frozenset({860})  # MGS 0014 El Olimpo

# ── Hardcoded node map: frt_code → (principal_node_id, respaldo_node_id) ──────
# Source: nodos.json from the Plataforma Central de Monitoreo.
# Key = frontera SIC code, Value = (principal, respaldo) — None if not registered.
FRONTERA_NODE_MAP: dict[str, tuple[int | None, int | None]] = {
    "frt55044": (603,  604),   # MINIGRANJA SOLAR BARAYA
    "frt55090": (609,  610),   # MINIGRANJA SOLAR GANDALF
    "frt55093": (606,  607),   # MINIGRANJA SOLAR CAÑAHUATE
    "frt58839": (845,  846),   # Minigranja 005 - La Paz Vallenata
    "frt60629": (848,  849),   # Minigranja Solar 0006 - Perijá
    "frt63879": (1022, 1020),  # Minigranja 0009 La Paz Verso
    "frt65205": (1283, 1282),  # Minigranja 0018 - La Paz Leyenda
    "frt66597": (1459, 1460),  # Minigranja 0017 - La Paz Esmeralda
    "frt_olimpo14": (860, None), # MGS 0014 - El Olimpo (solo principal registrado)
    "frt67475": (1481, 1482),  # MGS 0015 - El Son
    "frt67496": (1489, 1490),  # MGS 0019 - El Merengue
    "frt68269": (1514, 1515),  # MGS 0016 - La Puya
    "frt73414": (1590, 1591),  # MGS 0021 - Ibirico
    "frt74080": (1584, 1585),  # MGS 0022 - La Cumbia
    "frt76578": (1656, 1657),  # MGS 0024 - San Diego Sur
    "frt76581": (1654, 1655),  # MGS 0020 - El Mapalé
    "frt76586": (1658, 1659),  # MGS 0023 - El Joropo
    "frt82546": (1664, 1665),  # MGS 0027 - Valencia Oriente 2
    "frt82576": (1662, 1663),  # MGS 0025 - El Copey Occidente
    "frt82846": (1692, 1693),  # Sol&Cielo 7 Los Bongos
    "frt84587": (1712, 1713),  # GD San Pelayo
    "frt86234": (1660, 1661),  # MGS 0026 - Valencia Oriente
    "frt87017": (1722, 1723),  # MGS 0040 - La Cacica
    "frt87018": (1724, 1725),  # MGS 0041 - Las Piloneras
    "frt87336": (1716, 1717),  # La Catedral
    "frt89202": (1719, 1718),  # Sol&Cielo 9 - Ciénaga Generación
    "frt92219": (1730, 1731),  # MGS 0075 - Chiriguaná Norte 2
    "frt92221": (1739, 1740),  # MGS 0077 - Chiriguaná Norte 4
    "frt_reserva": (1578, 1577),  # La Reserva
}

# minigranja number → frontera code (for numbered projects)
_NUM_TO_FRT: dict[int, str] = {
    5:  "frt58839",
    6:  "frt60629",
    9:  "frt63879",
    14: "frt_olimpo14",
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

# keyword → frontera code
# Cubre proyectos cuyos nombres en BD no tienen el patrón "minigranja NNN" / "mgs NNN"
_KW_TO_FRT: dict[str, str] = {
    # Primeras minigranjas (sin número en el nombre comercial)
    "baraya":           "frt55044",
    "gandalf":          "frt55090",
    "canahuate":        "frt55093",
    # La Paz (varias — orden importa: más específico primero)
    "vallenata":        "frt58839",
    "perija":           "frt60629",
    "verso":            "frt63879",
    "leyenda":          "frt65205",
    "esmeralda":        "frt66597",
    # MGS con nombres propios
    "el son":           "frt67475",
    "merengue":         "frt67496",
    "la puya":          "frt68269",
    "ibirico":          "frt73414",
    "la cumbia":        "frt74080",
    "san diego sur":    "frt76578",
    "mapale":           "frt76581",
    "joropo":           "frt76586",
    "valencia oriente 2":"frt82546",
    "copey occidente":  "frt82576",
    "los bongos":       "frt82846",
    "san pelayo":       "frt84587",
    "valencia oriente": "frt86234",   # después de "valencia oriente 2"
    "la cacica":        "frt87017",
    "las piloneras":    "frt87018",
    "la catedral":      "frt87336",
    "cienaga generacion":"frt89202",
    "chiriquana norte 2":"frt92219",
    "chiriquana norte 4":"frt92221",
    "olimpo":           "frt_olimpo14",
    "la reserva":       "frt_reserva",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


def _mgs_number(name: str) -> int | None:
    m = re.search(r"(?:minigranja|mgs|mgr)\s+0*(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _find_frt(*names: str) -> str | None:
    """Resolve frontera code from project name(s)."""
    # Sort keywords longest-first so "valencia oriente 2" matches before "valencia oriente"
    _kw_sorted = sorted(_KW_TO_FRT.items(), key=lambda x: -len(x[0]))
    for name in names:
        if not name:
            continue
        num = _mgs_number(name)
        if num is not None:
            frt = _NUM_TO_FRT.get(num)
            if frt:
                return frt
        n = _norm(name)
        for kw, frt in _kw_sorted:
            if kw in n:
                return frt
    return None


def find_gaia_node_id(*names: str) -> int | None:
    """Find the principal Gaia node_id for a project. Returns None if not found."""
    frt = _find_frt(*names)
    if frt:
        pair = FRONTERA_NODE_MAP.get(frt)
        if pair:
            return pair[0]
    return None


def find_gaia_node_pair(*names: str) -> tuple[int | None, int | None]:
    """Find both (principal, respaldo) Gaia node IDs for a project.

    Returns (None, None) if no mapping is found.
    """
    frt = _find_frt(*names)
    if frt:
        pair = FRONTERA_NODE_MAP.get(frt)
        if pair:
            return pair
    return (None, None)


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

    def get_node_eae_today(self, node_id: int) -> float:
        """Return total exported energy [Wh] for node today (sum of eaepd1+2+3 across all rows)."""
        rows = self.get_node_measurements(node_id, _col_today(), "eae")
        total = 0.0
        for r in rows:
            for f in ("eaepd1", "eaepd2", "eaepd3"):
                v = r.get(f)
                if v is not None:
                    total += float(v)
        return total

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

        # Retorna None solo si no hay absolutamente ningún dato útil
        if not lv and not lc and not lap and not eae and not iae:
            return None

        # Most recent timestamp across all vars
        all_times = [r[-1].get("time") for r in results.values() if r]
        last_time = max((t for t in all_times if t), default=None)

        # ── Helpers ────────────────────────────────────────────────────────────
        def _phase_sum(row: dict, *fields: str) -> float | None:
            """Sum several phase fields from a single row; None if all absent."""
            vals = [float(row[f]) for f in fields if row.get(f) is not None]
            return sum(vals) if vals else None

        def _phase_avg(row: dict, *fields: str) -> float | None:
            vals = [float(row[f]) for f in fields if row.get(f) is not None]
            return sum(vals) / len(vals) if vals else None

        def _running_sum_series(data: list, *fields: str) -> list:
            """Cumulative sum of one or more fields across all rows → kWh timeline."""
            total = 0.0
            out = []
            for row in data:
                t = row.get("time")
                v = sum(float(row[f]) for f in fields if row.get(f) is not None)
                if t and v:
                    total += v
                    out.append({"time": t, "kwh": round(total / 1000, 3)})
            return out

        # ── Instantaneous values (last measurement row) ────────────────────────
        # Active power: API returns app1/app2/app3 (not ap1/ap2/ap3)
        ap1 = lap.get("app1")
        ap2 = lap.get("app2")
        ap3 = lap.get("app3")
        ap_total = _phase_sum(lap, "app1", "app2", "app3")

        # Reactive power: rpp1/rpp2/rpp3
        rp1 = lrp.get("rpp1")
        rp2 = lrp.get("rpp2")
        rp3 = lrp.get("rpp3")
        rp_total = _phase_sum(lrp, "rpp1", "rpp2", "rpp3")

        # Power factor: pfp1/pfp2/pfp3
        pf1 = lpf.get("pfp1")
        pf2 = lpf.get("pfp2")
        pf3 = lpf.get("pfp3")
        pf_avg = _phase_avg(lpf, "pfp1", "pfp2", "pfp3")

        # ── Detect AP unit: if any |app| value > 5000, values are in W ──────────
        _max_ap = max(
            (abs(float(r.get(f) or 0))
             for r in results["ap"]
             for f in ("app1", "app2", "app3")
             if r.get(f) is not None),
            default=0
        )
        _ap_divisor = 1000.0 if _max_ap > 5000 else 1.0

        # ── Time series for power chart → always kW ───────────────────────────
        power_series = [
            {"time": r["time"], "kw": round(
                sum(float(r.get(k) or 0) for k in ("app1", "app2", "app3")) / _ap_divisor, 3
            )}
            for r in results["ap"]
            if any(r.get(k) is not None for k in ("app1", "app2", "app3")) and r.get("time")
        ]

        # ── eae unit: nodos en _EAE_WH_NODES retornan Wh; el resto ya es kWh ──
        _eae_raw = _sum("eaepd1", "eaepd2", "eaepd3", data=eae)
        _eae_kwh = (round(_eae_raw / 1000.0, 3)
                    if (_eae_raw and node_id in _EAE_WH_NODES)
                    else _eae_raw)

        return {
            # Voltage per phase [V]  — vp1/vp2/vp3 correct
            "vp1": lv.get("vp1"), "vp2": lv.get("vp2"), "vp3": lv.get("vp3"),
            # Current per phase [A] — cp1/cp2/cp3 correct
            "cp1": lc.get("cp1"), "cp2": lc.get("cp2"), "cp3": lc.get("cp3"),
            # Active power [W]      — API: app1/app2/app3
            "ap1": ap1, "ap2": ap2, "ap3": ap3, "ap_total": ap_total,
            # Reactive power [VAR]  — API: rpp1/rpp2/rpp3
            "rp1": rp1, "rp2": rp2, "rp3": rp3, "rp_total": rp_total,
            # Power factor          — API: pfp1/pfp2/pfp3
            "pf1": pf1, "pf2": pf2, "pf3": pf3, "pf_avg": pf_avg,
            # Cumulative energy today [kWh] — unit-normalized
            "eae_wh":  _eae_kwh,
            "eae1_wh": _sum("eaepd1", data=eae),
            "eae2_wh": _sum("eaepd2", data=eae),
            "eae3_wh": _sum("eaepd3", data=eae),
            # Imported energy [Wh]        — API: iaepd1/iaepd2/iaepd3
            "iae_wh":  _sum("iaepd1", "iaepd2", "iaepd3", data=iae),
            "iae1_wh": _sum("iaepd1", data=iae),
            "iae2_wh": _sum("iaepd2", data=iae),
            "iae3_wh": _sum("iaepd3", data=iae),
            # Reactive exported [VARh]    — API: erepd1/erepd2/erepd3
            "ere_wh":  _sum("erepd1", "erepd2", "erepd3", data=ere),
            "ere1_wh": _sum("erepd1", data=ere),
            "ere2_wh": _sum("erepd2", data=ere),
            "ere3_wh": _sum("erepd3", data=ere),
            "last_time": last_time,
            # Time series for frontend charts
            "time_series": {
                "power":      power_series,
                "energy_exp": _running_sum_series(eae, "eaepd1", "eaepd2", "eaepd3"),
                "energy_imp": _running_sum_series(iae, "iaepd1", "iaepd2", "iaepd3"),
            },
        }
