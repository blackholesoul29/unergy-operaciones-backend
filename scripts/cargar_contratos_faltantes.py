"""
Crea los 8 contratos PPA faltantes en la plataforma Operaciones.
Uso: python scripts/cargar_contratos_faltantes.py [--dry-run]

Variables de entorno requeridas (o definidas en .env local):
  OPS_BASE_URL  — p.ej. https://backend-production-63d8.up.railway.app/api/v1
  OPS_EMAIL     — email de la cuenta admin
  OPS_PASSWORD  — contraseña
"""
import os
import sys
import calendar
import requests

BASE_URL = os.environ.get("OPS_BASE_URL", "https://backend-production-63d8.up.railway.app/api/v1")
EMAIL    = os.environ["OPS_EMAIL"]
PASSWORD = os.environ["OPS_PASSWORD"]
DRY_RUN  = "--dry-run" in sys.argv


# ── Auth ──────────────────────────────────────────────────────────────────────

def login():
    r = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ── API helpers ───────────────────────────────────────────────────────────────

def create_contrato(headers, payload):
    if DRY_RUN:
        print(f"  [DRY] CREATE contrato: {payload['numero_codigo_contrato']} – {payload.get('nombre_interno')}")
        return {"id": 9999}
    r = requests.post(f"{BASE_URL}/ppa", json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def set_tarifas(headers, contrato_id, rows):
    if DRY_RUN:
        print(f"  [DRY] TARIFAS contrato {contrato_id}: {len(rows)} filas")
        return
    r = requests.put(f"{BASE_URL}/ppa/{contrato_id}/tarifas", json=rows, headers=headers, timeout=15)
    r.raise_for_status()


def set_compromisos(headers, contrato_id, rows):
    if DRY_RUN:
        print(f"  [DRY] COMPROMISOS contrato {contrato_id}: {len(rows)} filas")
        return
    r = requests.put(f"{BASE_URL}/ppa/{contrato_id}/compromisos", json=rows, headers=headers, timeout=15)
    r.raise_for_status()


# ── Month iteration ───────────────────────────────────────────────────────────

def months_range(start_ym, end_ym):
    """Yields (year, month) from start_ym to end_ym inclusive."""
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


# ── NEU tariffs & compromisos ─────────────────────────────────────────────────
# Base rates per MGS for a 31-day month (contractual reference month)
NEU_MIN_DIARIO_POR_MGS = 128.681 / 31   # MWh/día/MGS
NEU_MAX_DIARIO_POR_MGS = 183.830 / 31   # MWh/día/MGS

NEU_TARIFA_SCHEDULE = [
    ((2024, 1),  (2025, 12), 338.0),
    ((2026, 1),  (2026, 12), 318.0),
    ((2027, 1),  (2027, 12), 305.0),
    ((2028, 1),  (2028, 12), 300.0),
    ((2029, 1),  (2029, 12), 290.0),
    ((2030, 1),  (2030, 12), 288.0),
    ((2031, 1),  (2031, 12), 284.0),
    ((2032, 1),  (2033, 12), 279.0),
    ((2034, 1),  (2035, 12), 275.0),
    ((2036, 1),  (2036, 12), 267.0),
    ((2037, 1),  (2037, 12), 258.4),
    ((2038, 1),  (2038, 12), 253.4),
    ((2039, 1),  (2039, 12), 247.4),
    ((2040, 1),  (2040, 12), 245.4),
]


def neu_tarifa(y, m):
    ym = (y, m)
    for s, e, t in NEU_TARIFA_SCHEDULE:
        if s <= ym <= e:
            return t
    return None


def neu1_mgs(y, m):
    ym = (y, m)
    if ym == (2024, 12):                              return 1
    if ym == (2025, 1):                               return 2
    if ym == (2025, 2):                               return 3
    if ym == (2025, 3):                               return 4
    if (2025, 4) <= ym <= (2040, 12):                 return 5
    return 0


def neu2_mgs(y, m):
    ym = (y, m)
    if ym == (2025, 3):                               return 1
    if (2025, 4) <= ym <= (2040, 12):                 return 2
    return 0


def neu_compromisos(mgs_fn, start_ym, end_ym):
    rows = []
    for y, m in months_range(start_ym, end_ym):
        n = mgs_fn(y, m)
        if n:
            days = calendar.monthrange(y, m)[1]
            rows.append({
                "año": y, "mes": m,
                "energia_minima": round(n * NEU_MIN_DIARIO_POR_MGS * days, 3),
                "energia_maxima": round(n * NEU_MAX_DIARIO_POR_MGS * days, 3),
            })
    return rows


def neu_tarifas(start_ym, end_ym):
    rows = []
    for y, m in months_range(start_ym, end_ym):
        t = neu_tarifa(y, m)
        if t is not None:
            rows.append({"año": y, "mes": m, "tarifa": t})
    return rows


# ── KLIK tariffs & compromisos ────────────────────────────────────────────────
KLIK_MIN_PER_MGS = 69.6
KLIK_MAX_PER_MGS = 174.0

KLIK_TARIFA_SCHEDULE = [
    ((2026, 4),  (2027, 3),  328.8),
    ((2027, 4),  (2028, 3),  308.8),
    ((2028, 4),  (2029, 3),  306.8),
    ((2029, 4),  (2030, 3),  303.0),
    ((2030, 4),  (2031, 3),  299.0),
    ((2031, 4),  (2032, 3),  298.0),
    ((2032, 4),  (2033, 3),  297.8),
    ((2033, 4),  (2034, 3),  293.7),
    ((2034, 4),  (2035, 3),  285.0),
    ((2035, 4),  (2036, 3),  278.8),
    ((2036, 4),  (2037, 3),  266.0),
    ((2037, 4),  (2038, 3),  260.5),
    ((2038, 4),  (2039, 3),  250.6),
    ((2039, 4),  (2040, 3),  247.0),
    ((2040, 4),  (2041, 3),  245.0),
]

LUMINA_TARIFA_SCHEDULE = [
    ((2026, 1),  (2026, 12), 330.0),
    ((2027, 1),  (2027, 12), 315.0),
    ((2028, 1),  (2028, 12), 312.8),
    ((2029, 1),  (2029, 12), 309.0),
    ((2030, 1),  (2030, 12), 307.8),
    ((2031, 1),  (2031, 12), 304.8),
    ((2032, 1),  (2032, 12), 302.0),
    ((2033, 1),  (2033, 12), 293.0),
    ((2034, 1),  (2034, 12), 290.0),
    ((2035, 1),  (2035, 12), 288.8),
    ((2036, 1),  (2036, 12), 286.0),
    ((2037, 1),  (2037, 12), 285.8),
    ((2038, 1),  (2038, 12), 282.0),
    ((2039, 1),  (2039, 12), 280.88),
    ((2040, 1),  (2041, 12), 260.0),
]


def _tarifa_from_schedule(schedule, y, m):
    ym = (y, m)
    for s, e, t in schedule:
        if s <= ym <= e:
            return t
    return None


def klik_mgs(y, m):
    ym = (y, m)
    if (2026, 4)  <= ym <= (2026, 9):  return 1
    if (2026, 10) <= ym <= (2028, 3):  return 2
    if (2028, 4)  <= ym <= (2033, 3):  return 3
    if (2033, 4)  <= ym <= (2041, 3):  return 4
    return 0


def lumina_mgs(y, m):
    ym = (y, m)
    if (2026, 8)  <= ym <= (2026, 12): return 1
    if (2027, 1)  <= ym <= (2031, 12): return 2
    if (2032, 1)  <= ym <= (2034, 12): return 3
    if (2035, 1)  <= ym <= (2036, 12): return 4
    if (2037, 1)  <= ym <= (2041, 12): return 5
    return 0


def fixed_compromisos(mgs_fn, start_ym, end_ym):
    """Fixed MWh per MGS per month (KLIK/Lumina style — not day-scaled)."""
    rows = []
    for y, m in months_range(start_ym, end_ym):
        n = mgs_fn(y, m)
        if n:
            rows.append({
                "año": y, "mes": m,
                "energia_minima": round(n * KLIK_MIN_PER_MGS, 3),
                "energia_maxima": round(n * KLIK_MAX_PER_MGS, 3),
            })
    return rows


def gen_tarifas(schedule, start_ym, end_ym):
    rows = []
    for y, m in months_range(start_ym, end_ym):
        t = _tarifa_from_schedule(schedule, y, m)
        if t is not None:
            rows.append({"año": y, "mes": m, "tarifa": t})
    return rows


# ── Contract definitions ──────────────────────────────────────────────────────

CONTRATOS = [
    {
        "meta": {"nombre": "NEU I"},
        "payload": {
            "numero_codigo_contrato": "MNRNEU-2024-005",
            "nombre_interno": "NEU I",
            "comprador_nombre": "NEU I S.A.S. E.S.P.",
            "fecha_inicio": "2024-12-01",
            "fecha_fin": "2040-12-31",
        },
        "tarifas_fn": lambda: neu_tarifas((2024, 12), (2040, 12)),
        "compromisos_fn": lambda: neu_compromisos(neu1_mgs, (2024, 12), (2040, 12)),
    },
    {
        "meta": {"nombre": "NEU II"},
        "payload": {
            "numero_codigo_contrato": "MNRNEU-2024-006",
            "nombre_interno": "NEU II",
            "comprador_nombre": "NEU II S.A.S. E.S.P.",
            "fecha_inicio": "2025-03-01",
            "fecha_fin": "2040-12-31",
        },
        "tarifas_fn": lambda: neu_tarifas((2025, 3), (2040, 12)),
        "compromisos_fn": lambda: neu_compromisos(neu2_mgs, (2025, 3), (2040, 12)),
    },
    {
        "meta": {"nombre": "KLIK"},
        "payload": {
            "numero_codigo_contrato": "OM-UNERGY-010-2025",
            "nombre_interno": "KLIK",
            "comprador_nombre": "BEAM ENERGY INNOVATION S.A.S. E.S.P.",
            "fecha_inicio": "2026-04-01",
            "fecha_fin": "2041-03-31",
        },
        "tarifas_fn": lambda: gen_tarifas(KLIK_TARIFA_SCHEDULE, (2026, 4), (2041, 3)),
        "compromisos_fn": lambda: fixed_compromisos(klik_mgs, (2026, 4), (2041, 3)),
    },
    {
        "meta": {"nombre": "Lumina"},
        "payload": {
            "numero_codigo_contrato": "OM-UNERGY-011-2025",
            "nombre_interno": "Lumina",
            "comprador_nombre": "LUMINA ENERGY S.A.S. E.S.P.",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2041-12-31",
        },
        "tarifas_fn": lambda: gen_tarifas(LUMINA_TARIFA_SCHEDULE, (2026, 8), (2041, 12)),
        "compromisos_fn": lambda: fixed_compromisos(lumina_mgs, (2026, 8), (2041, 12)),
    },
    {
        "meta": {"nombre": "Enermas"},
        "payload": {
            "numero_codigo_contrato": "NMRG-UNGG-001-2025",
            "nombre_interno": "Enermas",
            "comprador_nombre": "ENERMAS S.A.S. E.S.P.",
            "fecha_inicio": "2025-04-03",
            "fecha_fin": "2030-03-31",
        },
        "tarifas_fn": lambda: [],
        "compromisos_fn": lambda: [],
    },
    {
        "meta": {"nombre": "Santa Fe 1"},
        "payload": {
            "numero_codigo_contrato": "OM-SFE-UNERGY-001-2025",
            "nombre_interno": "Santa Fe 1",
            "comprador_nombre": "SANTA FE ENERGY ZOMAC S.A.S. E.S.P.",
            "fecha_inicio": "2025-06-01",
            "fecha_fin": "2025-12-31",
        },
        "tarifas_fn": lambda: [],
        "compromisos_fn": lambda: [],
    },
    {
        "meta": {"nombre": "Santa Fe 2"},
        "payload": {
            "numero_codigo_contrato": "OMCE-SFE-UNERGY-002-2025",
            "nombre_interno": "Santa Fe 2",
            "comprador_nombre": "SANTA FE ENERGY ZOMAC S.A.S. E.S.P.",
            "fecha_inicio": "2026-01-01",
            "fecha_fin": "2037-12-31",
        },
        "tarifas_fn": lambda: [],
        "compromisos_fn": lambda: [],
    },
    {
        "meta": {"nombre": "Nitro Energy"},
        "payload": {
            "numero_codigo_contrato": "OC.UNER-063-2025",
            "nombre_interno": "Nitro Energy",
            "comprador_nombre": "NITRO ENERGY COLOMBIA S.A.S. E.S.P.",
            "fecha_inicio": "2026-01-01",
            "fecha_fin": "2040-12-31",
        },
        "tarifas_fn": lambda: [],
        "compromisos_fn": lambda: [],
    },
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[1/2] Autenticando...")
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    ok = err = 0
    for c in CONTRATOS:
        nombre = c["meta"]["nombre"]
        print(f"\n-- {nombre} --")
        try:
            created = create_contrato(headers, c["payload"])
            cid = created["id"]
            print(f"    id={cid}")

            tarifas = c["tarifas_fn"]()
            if tarifas:
                set_tarifas(headers, cid, tarifas)
                print(f"    tarifas: {len(tarifas)} meses")
            else:
                print("    tarifas: pendiente")

            compromisos = c["compromisos_fn"]()
            if compromisos:
                set_compromisos(headers, cid, compromisos)
                print(f"    compromisos: {len(compromisos)} meses")
            else:
                print("    compromisos: pendiente")

            ok += 1
        except Exception as e:
            print(f"    [ERR] {e}")
            err += 1

    print(f"\n[DONE] OK={ok}  ERR={err}")


if __name__ == "__main__":
    main()
