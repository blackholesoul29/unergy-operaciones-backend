"""
Carga la Hoja 6 de GESCON.xlsx (cambios de contratos) en asic_cambios_contratos.
Uso: python scripts/cargar_gescon_hoja6.py [--dry-run]
"""
import os
import sys, re
from datetime import datetime
import requests
import openpyxl

XLSX = r"C:\Users\juan_\OneDrive\Documentos\Dev\cumplimiento\GESCON\GESCON.xlsx"
BASE_URL = "https://backend-production-63d8.up.railway.app/api/v1"
EMAIL = os.environ.get("ADMIN_USER", "juanjose@unergy.io")
PASSWORD = os.environ.get("ADMIN_PASS", "")
DRY_RUN  = "--dry-run" in sys.argv


def sic_str(v):
    if v is None:
        return None
    try:
        return str(int(float(v)))
    except (ValueError, TypeError):
        return str(v).strip() or None


def safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def extract_frt(s):
    """Extracts 'frt69663' from 'Reserva(frt69663)' or 'Verso (FRT63879)'."""
    if not s:
        return None
    m = re.search(r'[Ff][Rr][Tt]\d+', str(s))
    return m.group(0).lower() if m else None


def login():
    r = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    print("[1/3] Autenticando...")
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    print("[2/3] Leyendo Hoja 6...")
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Hoja 6"]
    # Row 1 = "CAMBIOS", Row 2 = headers, data starts row 3
    # Cols: SIC, Contrato, Planta, Energia orig, Nueva planta, Energia nueva, Accion, Archivo
    filas = [r for r in ws.iter_rows(min_row=3, values_only=True) if any(v is not None for v in r[:4])]
    print(f"      {len(filas)} filas")

    ok = err = 0
    print("[3/3] Insertando...")
    for i, r in enumerate(filas):
        (sic, contrato, planta_orig, energia_orig,
         planta_nueva, energia_nueva, accion, archivo) = (list(r) + [None]*8)[:8]

        payload = {
            "codigo_sic_contrato": sic_str(sic),
            "contrato_interno": str(contrato).strip() if contrato else None,
            "codigo_frt_original": extract_frt(planta_orig),
            "energia_mensual_mwh_original": safe_float(energia_orig),
            "energia_mensual_mwh_nuevo": safe_float(energia_nueva),
            "accion": str(accion).strip() if accion else None,
            "nombre_archivo": str(archivo).strip() if archivo else None,
        }

        if DRY_RUN:
            print(f"  [DRY] SIC={payload['codigo_sic_contrato']} | {contrato} | {planta_orig} -> {planta_nueva} | {accion}")
            ok += 1
            continue

        try:
            resp = requests.post(f"{BASE_URL}/asic/cambios", json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            ok += 1
            print(f"  [OK] SIC={payload['codigo_sic_contrato']} | {contrato} | {accion}")
        except Exception as e:
            body = ""
            try:
                body = resp.text[:200]
            except Exception:
                pass
            print(f"  [ERR] fila {i+3}: {e} | {body}")
            err += 1

    print(f"\n[DONE] OK={ok}  ERR={err}")


if __name__ == "__main__":
    main()
