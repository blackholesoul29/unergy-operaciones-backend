"""
Load historical climate indices and XM energy prices into operaciones DB.

Usage:
    DATABASE_PUBLIC_URL=postgresql://... python3 scripts/cargar_clima_precios.py

Data sources (on EVO-X2):
    - /home/eduardo/Claude/clima/data/raw/noaa_sst/oni.csv
    - /home/eduardo/Claude/clima/data/raw/noaa_sst/soi.csv
    - /home/eduardo/Claude/clima/data/raw/noaa_sst/pdo.csv
    - /home/eduardo/Claude/clima/data/raw/noaa_sst/mjo_amplitude.csv
    - /home/eduardo/Claude/clima/data/raw/xm_energy/xm_monthly_prices.csv
    - /home/eduardo/Claude/clima/data/raw/chirps/chirps_colombia_monthly.nc
"""
import os
import sys
import csv
from pathlib import Path

import psycopg

DB_URL = os.environ.get("DATABASE_PUBLIC_URL", "")
if not DB_URL:
    print("ERROR: Set DATABASE_PUBLIC_URL env var")
    sys.exit(1)

CLIMA_DATA = Path("/home/eduardo/Claude/clima/data/raw")

REGIONS = {
    "Caribe": {"lat": (7, 13), "lon": (-77, -71)},
    "Andina": {"lat": (2, 8), "lon": (-77, -73)},
    "Pacifica": {"lat": (1, 8), "lon": (-79, -77)},
    "Orinoquia": {"lat": (2, 7), "lon": (-73, -67)},
    "Amazonia": {"lat": (-4, 2), "lon": (-75, -67)},
}


def read_index_csv(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                year = int(r["year"])
                month = int(r["month"])
                value = float(r["value"])
                rows.append((year, month, value))
            except (ValueError, KeyError):
                continue
    return rows


def classify_enso(oni):
    if oni <= -0.5:
        return "La Niña"
    elif oni >= 0.5:
        return "El Niño"
    return "Neutral"


def load_oni(conn):
    oni_data = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/oni.csv")}
    soi_data = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/soi.csv")}
    pdo_data = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/pdo.csv")}
    mjo_data = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/mjo_amplitude.csv")}

    count = 0
    with conn.cursor() as cur:
        for (year, month), oni in sorted(oni_data.items()):
            cur.execute("""
                INSERT INTO clima_oni_monthly (year, month, oni_value, soi_value, pdo_value, mjo_amplitude, enso_phase)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (year, month) DO UPDATE SET
                    oni_value = EXCLUDED.oni_value,
                    soi_value = EXCLUDED.soi_value,
                    pdo_value = EXCLUDED.pdo_value,
                    mjo_amplitude = EXCLUDED.mjo_amplitude,
                    enso_phase = EXCLUDED.enso_phase
            """, (
                year, month, oni,
                soi_data.get((year, month)),
                pdo_data.get((year, month)),
                mjo_data.get((year, month)),
                classify_enso(oni),
            ))
            count += 1
    conn.commit()
    print(f"  clima_oni_monthly: {count} rows")


def load_precip(conn):
    try:
        import xarray as xr
        import numpy as np
    except ImportError:
        print("  SKIP clima_precip_monthly — xarray not installed")
        return

    ds = xr.open_dataset(CLIMA_DATA / "chirps/chirps_colombia_monthly.nc")
    count = 0

    climatology = {}
    for region_name, bounds in REGIONS.items():
        regional = ds["precip"].sel(
            latitude=slice(*bounds["lat"]),
            longitude=slice(*bounds["lon"]),
        )
        monthly_mean = regional.mean(dim=["latitude", "longitude"])
        clim = monthly_mean.sel(time=slice("1991", "2020")).groupby("time.month").mean()
        climatology[region_name] = {int(m): float(v) for m, v in zip(clim.month.values, clim.values) if not np.isnan(v)}

    with conn.cursor() as cur:
        for region_name, bounds in REGIONS.items():
            regional = ds["precip"].sel(
                latitude=slice(*bounds["lat"]),
                longitude=slice(*bounds["lon"]),
            )
            monthly = regional.mean(dim=["latitude", "longitude"])
            for t, v in zip(monthly.time.values, monthly.values):
                if np.isnan(v):
                    continue
                ts = str(t)[:10]
                year = int(ts[:4])
                month = int(ts[5:7])
                clim_val = climatology[region_name].get(month, v)
                anomaly = ((v - clim_val) / clim_val * 100) if clim_val > 0 else 0

                cur.execute("""
                    INSERT INTO clima_precip_monthly (year, month, region, precip_mm, anomaly_pct, climatology_mm)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (year, month, region) DO UPDATE SET
                        precip_mm = EXCLUDED.precip_mm,
                        anomaly_pct = EXCLUDED.anomaly_pct,
                        climatology_mm = EXCLUDED.climatology_mm
                """, (year, month, region_name, float(v), round(anomaly, 1), round(clim_val, 1)))
                count += 1
    conn.commit()
    print(f"  clima_precip_monthly: {count} rows")


def load_prices(conn):
    oni_data = {(y, m): v for y, m, v in read_index_csv(CLIMA_DATA / "noaa_sst/oni.csv")}

    count = 0
    with conn.cursor() as cur:
        with open(CLIMA_DATA / "xm_energy/xm_monthly_prices.csv") as f:
            reader = csv.DictReader(f)
            for r in reader:
                date_str = r["date"]
                price = float(r["price_cop_kwh"])
                year = int(date_str[:4])
                month = int(date_str[5:7])
                oni = oni_data.get((year, month))
                phase = classify_enso(oni) if oni is not None else None

                cur.execute("""
                    INSERT INTO clima_price_monthly (year, month, price_cop_kwh, enso_phase)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (year, month) DO UPDATE SET
                        price_cop_kwh = EXCLUDED.price_cop_kwh,
                        enso_phase = EXCLUDED.enso_phase
                """, (year, month, price, phase))
                count += 1
    conn.commit()
    print(f"  clima_price_monthly: {count} rows")


def main():
    print(f"Connecting to: {DB_URL[:50]}...")
    conn_url = DB_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(conn_url) as conn:
        print("Loading climate indices...")
        load_oni(conn)

        print("Loading precipitation...")
        load_precip(conn)

        print("Loading XM prices...")
        load_prices(conn)

        print("\nDone! All historical data loaded.")


if __name__ == "__main__":
    main()
