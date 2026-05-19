"""
Load historical climate + price data into Railway DB via the backend API.
Bypasses direct DB connection (Railway public networking not enabled).

Usage:
    python3 scripts/cargar_clima_via_api.py
"""
import csv
import json
import sys
from pathlib import Path

import httpx

BACKEND_URL = "https://backend-production-63d8.up.railway.app"
CLIMA_DATA = Path("/home/eduardo/Claude/clima/data/raw")

REGIONS = {
    "Caribe": {"lat": (7, 13), "lon": (-77, -71)},
    "Andina": {"lat": (2, 8), "lon": (-77, -73)},
    "Pacifica": {"lat": (1, 8), "lon": (-79, -77)},
    "Orinoquia": {"lat": (2, 7), "lon": (-73, -67)},
    "Amazonia": {"lat": (-4, 2), "lon": (-75, -67)},
}


def classify_enso(oni):
    if oni <= -0.5:
        return "La Niña"
    elif oni >= 0.5:
        return "El Niño"
    return "Neutral"


def read_index_csv(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append((int(r["year"]), int(r["month"]), float(r["value"])))
            except (ValueError, KeyError):
                continue
    return rows


def get_token():
    resp = httpx.post(f"{BACKEND_URL}/api/v1/auth/token",
        data={"username": "eduardo@unergy.io", "password": "Unergy2025!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def prepare_oni():
    oni = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/oni.csv")}
    soi = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/soi.csv")}
    pdo = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/pdo.csv")}
    mjo = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/mjo_amplitude.csv")}

    rows = []
    for (year, month), val in sorted(oni.items()):
        rows.append({
            "year": year, "month": month, "oni": val,
            "soi": soi.get((year, month)),
            "pdo": pdo.get((year, month)),
            "mjo": mjo.get((year, month)),
            "phase": classify_enso(val),
        })
    return rows


def prepare_precip():
    try:
        sys.path.insert(0, "/home/eduardo/Claude/clima/.venv/lib/python3.12/site-packages")
        import xarray as xr
        import numpy as np
    except ImportError:
        print("  SKIP precip — xarray not available")
        return []

    ds = xr.open_dataset(CLIMA_DATA / "chirps/chirps_colombia_monthly.nc")
    rows = []

    climatology = {}
    for name, bounds in REGIONS.items():
        regional = ds["precip"].sel(latitude=slice(*bounds["lat"]), longitude=slice(*bounds["lon"]))
        clim = regional.mean(dim=["latitude", "longitude"]).sel(time=slice("1991", "2020")).groupby("time.month").mean()
        climatology[name] = {int(m): float(v) for m, v in zip(clim.month.values, clim.values) if not np.isnan(v)}

    for name, bounds in REGIONS.items():
        regional = ds["precip"].sel(latitude=slice(*bounds["lat"]), longitude=slice(*bounds["lon"]))
        monthly = regional.mean(dim=["latitude", "longitude"])
        for t, v in zip(monthly.time.values, monthly.values):
            if np.isnan(v):
                continue
            ts = str(t)[:10]
            year, month = int(ts[:4]), int(ts[5:7])
            clim_val = climatology[name].get(month, float(v))
            anomaly = ((float(v) - clim_val) / clim_val * 100) if clim_val > 0 else 0
            rows.append({
                "year": year, "month": month, "region": name,
                "precip_mm": round(float(v), 1),
                "anomaly_pct": round(anomaly, 1),
                "climatology_mm": round(clim_val, 1),
            })
    return rows


def prepare_prices():
    oni = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/oni.csv")}
    rows = []
    with open(CLIMA_DATA / "xm_energy/xm_monthly_prices.csv") as f:
        reader = csv.DictReader(f)
        for r in reader:
            year, month = int(r["date"][:4]), int(r["date"][5:7])
            price = float(r["price_cop_kwh"])
            o = oni.get((year, month))
            rows.append({
                "year": year, "month": month,
                "price_cop_kwh": round(price, 2),
                "enso_phase": classify_enso(o) if o is not None else None,
                "precip_andina_mm": None,
            })
    return rows


def main():
    print("Authenticating...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    print("Preparing ONI data...")
    oni = prepare_oni()
    print(f"  {len(oni)} ONI rows")

    print("Preparing precipitation data...")
    precip = prepare_precip()
    print(f"  {len(precip)} precip rows")

    print("Preparing XM price data...")
    prices = prepare_prices()
    print(f"  {len(prices)} price rows")

    # Send in chunks to avoid timeout
    chunk_size = 500
    total = {"oni": 0, "precip": 0, "prices": 0}

    for i in range(0, max(len(oni), len(precip), len(prices)), chunk_size):
        payload = {
            "oni": oni[i:i+chunk_size],
            "precip": precip[i:i+chunk_size],
            "prices": prices[i:i+chunk_size],
        }
        if not any(payload.values()):
            continue
        print(f"  Sending chunk {i//chunk_size + 1}...")
        resp = httpx.post(
            f"{BACKEND_URL}/api/v1/evo/clima/bulk-load",
            json=payload, headers=headers, timeout=60,
        )
        if resp.status_code != 200:
            print(f"  ERROR: {resp.status_code} {resp.text[:200]}")
            continue
        r = resp.json()
        for k in total:
            total[k] += r["loaded"].get(k, 0)
        print(f"  OK: {r['loaded']}")

    print(f"\nDone! Total loaded: {total}")


if __name__ == "__main__":
    main()
