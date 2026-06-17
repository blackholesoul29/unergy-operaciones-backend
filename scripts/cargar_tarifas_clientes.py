"""
Carga tarifa_administracion, tarifa_cgm y tarifa_representacion en la tabla clientes.

Uso:
    python scripts/cargar_tarifas_clientes.py [--dry-run] [--force]
"""
import os
import sys
import unicodedata
from difflib import SequenceMatcher
import requests

BASE = "https://backend-production-63d8.up.railway.app"
USER = os.environ.get("ADMIN_USER", "juanjose@unergy.io")
PASS = os.environ.get("ADMIN_PASS", "")

args = sys.argv[1:]
FORCE   = "--force"   in args
DRY_RUN = "--dry-run" in args

# ---------------------------------------------------------------------------
# Datos: (nombre_cliente, adm%, cgm%, rep%)
# adm% = tarifa_administracion = tarifa_operacion
# ---------------------------------------------------------------------------
REFERENCIA = [
    ("Solenium S.A.S",                                             3.80, 5.00, 5.00),
    ("Ayurá S.A.S.",                                               3.80, 5.00, 5.00),
    ("SAMBA SOLAR S.A.S.",                                         0.00, 5.50, 5.50),
    ("PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",     3.80, 6.00, 6.00),
    ("INVERSIONES BIOSOSTENIBLES S.A.S.",                          0.00, 6.00, 6.00),
    ("Energy Investment Group SAS",                                0.00, 6.00, 6.00),
    ("INENERGY S.A.S",                                             0.00, 6.00, 6.00),
    ("QUANTUM ENERGY INGENIERIA S.A.S.",                           0.00, 6.00, 6.00),
    ("PELLETCO S.A.S.",                                            0.00, 6.00, 6.00),
    ("ENEXA ENERGY S.A.S.",                                        0.00, 5.00, 5.00),
    ("FEM ENERGIA S.A.S.",                                         0.00, 5.00, 6.00),
    ("FONSAR S.A.S.",                                              0.00, 6.00, 6.00),
    ("GRANJA SOLAR POLARIS 2 S.A.S.",                              0.00, 7.00, 3.00),
    ("GRANJAS SOLARES DELTA S.A.S. E.S.P",                        0.00, 7.00, 3.00),
    ("LA HORMIGA SOLAR S.A.S. E.S.P.",                             0.00, 5.50, 5.50),
    ("GRANJA SOLAR POLARIS ENERGY S.A.S.",                         0.00, 7.00, 3.00),
    ("NOVAVALOR ENERGY SAS",                                       0.00, 0.00, 6.00),
    ("PARQUE EOLICO DE GALERAZAMBA S.A.S.",                        0.00, 0.00, 6.00),
    ("FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA", 3.80, 0.00, 0.00),
    ("UNERGY S.A.S",                                               3.00, 5.00, 5.00),
    ("INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C",                 3.80, 6.00, 6.00),
    ("STRADA ASOCIADOS S A S",                                     3.80, 6.00, 6.00),
    ("GD EL REMOLINO 1 S.A.S. E.S.P.",                             0.00, 6.00, 6.00),
    ("NACIONAL DE TRANSFORMADORES S.A.S",                          3.80, 6.00, 6.00),
    ("Nitro Energy",                                               0.00, 0.00, 0.00),
    ("PROMOTORA DE ENERGIA ELECTRICA DE CARTAGENA S.A.S E.S.P.",   0.00, 6.00, 0.00),
    ("SOMOS BOGOTA USME SAS",                                      3.00, 6.00, 6.00),
]

THRESHOLD = 0.75


def norm(s):
    s = s.lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def get_token():
    r = requests.post(f"{BASE}/api/v1/auth/token",
                      data={"username": USER, "password": PASS}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_all_clientes(headers):
    r = requests.get(f"{BASE}/api/v1/clientes?size=500", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["items"]


def patch_cliente(cid, payload, headers):
    r = requests.patch(f"{BASE}/api/v1/clientes/{cid}",
                       json=payload, headers=headers, timeout=30)
    r.raise_for_status()


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Cargando tarifas en clientes...\n")

    print("  Autenticando...", end=" ", flush=True)
    headers = get_token()
    print("OK")

    print("  Cargando clientes...", end=" ", flush=True)
    clientes = get_all_clientes(headers)
    print(f"{len(clientes)} clientes\n")

    updated = skipped = no_match = 0
    no_match_list = []

    for nombre_ref, adm, cgm, rep in REFERENCIA:
        # buscar mejor match
        best_c, best_s = None, 0.0
        for c in clientes:
            s = sim(nombre_ref, c["razon_social_nombre"])
            if s > best_s:
                best_s = s
                best_c = c

        if not best_c or best_s < THRESHOLD:
            print(f"  NO-MATCH  '{nombre_ref}'  (mejor score: {best_s:.2f})")
            no_match += 1
            no_match_list.append(nombre_ref)
            continue

        payload = {}
        if best_c.get("tarifa_administracion") is None or FORCE:
            payload["tarifa_administracion"] = adm
        if best_c.get("tarifa_cgm") is None or FORCE:
            payload["tarifa_cgm"] = cgm
        if best_c.get("tarifa_representacion") is None or FORCE:
            payload["tarifa_representacion"] = rep

        if payload:
            print(f"  UPDATE  '{best_c['razon_social_nombre']}'  (ref: '{nombre_ref}', score: {best_s:.2f})")
            for k, v in payload.items():
                print(f"          {k}: {v}")
            if not DRY_RUN:
                patch_cliente(best_c["id"], payload, headers)
            updated += 1
        else:
            print(f"  OK      '{best_c['razon_social_nombre']}' — sin cambios")
            skipped += 1

    print(f"\n{tag}Resultado: {updated} actualizados, {skipped} sin cambios, {no_match} sin match.")
    if no_match_list:
        print(f"\nSin match ({len(no_match_list)}):")
        for n in no_match_list:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
