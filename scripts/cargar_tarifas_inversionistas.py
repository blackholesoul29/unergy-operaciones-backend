"""
Carga tarifas de servicios en proyecto_inversionistas vía API REST.
Campos: tarifa_administracion (= tarifa_operacion), tarifa_cgm, tarifa_representacion.

Lookup: proyecto por nombre_comercial (exacto), inversionista por cliente_nombre (fuzzy).

Uso:
    python scripts/cargar_tarifas_inversionistas.py [--dry-run] [--force]
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
# Datos: (nombre_proyecto, nombre_cliente, adm%, cgm%, rep%)
# adm% es también tarifa_operacion (mismo valor según instrucción)
# ---------------------------------------------------------------------------
REFERENCIA = [
    ("MGS 0025 - El Copey Occidente",      "Solenium S.A.S",                                              3.80, 5.00, 5.00),
    ("MGS 0025 - El Copey Occidente",      "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("GD San Pelayo",                      "SAMBA SOLAR S.A.S.",                                          0.00, 5.50, 5.50),
    ("MGS 0077 - Chiriguana Norte 4",      "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",      3.80, 6.00, 6.00),
    ("MGS 0075 - Chiriguana Norte 2",      "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",      3.80, 6.00, 6.00),
    ("MGS 0022 - La Cumbia",               "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("GD Biosolar",                        "INVERSIONES BIOSOSTENIBLES S.A.S.",                           0.00, 6.00, 6.00),
    ("GD Astrolumen La Garita",            "Energy Investment Group SAS",                                 0.00, 6.00, 6.00),
    ("Sol&Cielo 9 - Cienaga",              "INENERGY S.A.S",                                              0.00, 6.00, 6.00),
    ("Sol Y Cielo 7 Los Bongos",           "INENERGY S.A.S",                                              0.00, 6.00, 6.00),
    ("GD Sirius",                          "QUANTUM ENERGY INGENIERIA S.A.S.",                            0.00, 6.00, 6.00),
    ("La Catedral",                        "PELLETCO S.A.S.",                                             0.00, 6.00, 6.00),
    ("MGS 0041 Piloneras",                 "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0040 Cacica",                    "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0027 Valencia Oriente 2",        "Solenium S.A.S",                                              3.80, 5.00, 5.00),
    ("MGS 0026 Valencia Oriente 1",        "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("Cedillanos_excedentes",              "Ayurá S.A.S.",                                                0.00, 0.00, 0.00),
    ("PSF - Yurbaqua",                     "ENEXA ENERGY S.A.S",                                          0.00, 5.00, 5.00),
    ("GD Yuan Solar",                      "FEM ENERGIA S.A.S.",                                          0.00, 5.00, 6.00),
    ("MGS 0024 - San Diego Sur",           "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0024 - San Diego Sur",           "Solenium S.A.S",                                              3.80, 5.00, 5.00),
    ("MGS 0013 La Mesa",                   "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("GD Agustin 1",                       "FONSAR S.A.S.",                                               0.00, 6.00, 6.00),
    ("GD Polaris 2",                       "GRANJA SOLAR POLARIS 2 S.A.S.",                               0.00, 7.00, 3.00),
    ("GD delta 2",                         "GRANJAS SOLARES DELTA S.A.S. E.S.P",                          0.00, 7.00, 3.00),
    ("GD Marimonda",                       "LA HORMIGA SOLAR S.A.S. E.S.P.",                              0.00, 5.50, 5.50),
    ("MGS 0014 - El Olimpo",               "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("GD Delta 1",                         "GRANJAS SOLARES DELTA S.A.S. E.S.P",                          0.00, 7.00, 3.00),
    ("GD Polaris 1",                       "GRANJA SOLAR POLARIS ENERGY S.A.S.",                          0.00, 7.00, 3.00),
    ("GD 1MVA SAN ONOFRE",                 "NOVAVALOR ENERGY SAS",                                        0.00, 0.00, 6.00),
    ("Bayunca",                            "PARQUE EOLICO DE GALERAZAMBA S.A.S.",                         0.00, 0.00, 6.00),
    ("MGS Mapale",                         "FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",3.80, 0.00, 0.00),
    ("MGS 0023 Joropo",                    "Solenium S.A.S",                                              3.80, 0.00, 0.00),
    ("MGS 0023 Joropo",                    "Ayurá S.A.S.",                                                3.80, 0.00, 0.00),
    ("MGS 0030 Chima Oriente",             "Solenium S.A.S",                                              3.80, 0.00, 0.00),
    ("MGS 0030 Chima Oriente",             "Ayurá S.A.S.",                                                3.80, 0.00, 0.00),
    ("MGS 0021 Ibirico",                   "FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",3.80, 6.00, 6.00),
    ("Minigranja Solar Uruaco",            "UNERGY S.A.S",                                                3.00, 5.00, 5.00),
    ("MGS 0012 La Reserva",          "INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C",                  3.80, 6.00, 6.00),
    ("MGS 0012 La Reserva",          "STRADA ASOCIADOS S A S",                                      3.80, 6.00, 6.00),
    ("MGS 0019 El Merengue",               "Solenium S.A.S",                                              3.80, 5.00, 5.00),
    ("MGS 0019 El Merengue",               "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS Naos 3",                         "GD EL REMOLINO 1 S.A.S. E.S.P.",                              0.00, 6.00, 6.00),
    ("MGS 0018 La Paz Leyenda",            "Solenium S.A.S",                                              3.80, 6.00, 6.00),
    ("Minigranja Solar El Son",            "UNERGY S.A.S",                                                3.00, 6.00, 6.00),
    ("MGS 0016 - Puya",                    "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0010 - Villanueva",              "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS Naos 2",                         "GD EL REMOLINO 1 S.A.S. E.S.P.",                              0.00, 6.00, 6.00),
    ("Minigranja Solar El Son",            "Solenium S.A.S",                                              3.80, 6.00, 6.00),
    ("Minigranja Solar El Son",            "NACIONAL DE TRANSFORMADORES S.A.S",                           3.80, 6.00, 6.00),
    ("MGS 0017- Esmeralda",                "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("Minigranja Solar San Pedro",         "Nitro Energy",                                                0.00, 0.00, 0.00),
    ("MGS 0008 La Paz Verso",              "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("Minigranja Solar Uruaco",            "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("Minigranja Solar Baraya",            "UNERGY S.A.S",                                                3.80, 6.00, 6.00),
    ("MGS 0011 El Roble",                  "PROMOTORA DE ENERGIA ELECTRICA DE CARTAGENA S.A.S E.S.P.",    0.00, 6.00, 0.00),
    ("GD NAOS 1",                          "GD EL REMOLINO 1 S.A.S. E.S.P.",                              0.00, 7.00, 3.00),
    ("Minigranja Solar Baraya",            "SOMOS BOGOTÁ USME SAS",                                       3.00, 6.00, 6.00),
    ("Minigranja Solar Baraya",            "Solenium S.A.S",                                              3.80, 6.00, 6.00),
    ("MGS 0009 El Molino",                 "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0007 La Paz Vallenata",          "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0006 Perija",                    "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0005 Canahuate",                 "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
    ("MGS 0004 Valle de Gandalf",          "Ayurá S.A.S.",                                                3.80, 5.00, 5.00),
]

THRESHOLD = 0.65


def norm(s):
    s = s.lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def best_inv(cliente_ref, inversionistas):
    best, score = None, 0.0
    for inv in inversionistas:
        s = sim(cliente_ref, inv.get("cliente_nombre", ""))
        if s > score:
            score = s
            best = inv
    return (best, score) if score >= THRESHOLD else None


def get_token():
    r = requests.post(f"{BASE}/api/v1/auth/token",
                      data={"username": USER, "password": PASS}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_all_proyectos(headers):
    r = requests.get(f"{BASE}/api/v1/proyectos?size=500", headers=headers, timeout=30)
    r.raise_for_status()
    return {p["nombre_comercial"]: p for p in r.json()["items"]}


def patch_inversionista(pid, inv_id, payload, headers):
    r = requests.patch(f"{BASE}/api/v1/proyectos/{pid}/inversionistas/{inv_id}",
                       json=payload, headers=headers, timeout=30)
    r.raise_for_status()


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Cargando tarifas de inversionistas...\n")

    print("  Autenticando...", end=" ", flush=True)
    headers = get_token()
    print("OK")

    print("  Cargando proyectos...", end=" ", flush=True)
    by_nombre = get_all_proyectos(headers)
    print(f"{len(by_nombre)} proyectos\n")

    # índice por nombre_comercial exacto + fallback fuzzy para el proyecto
    def find_proyecto(nombre_ref):
        if nombre_ref in by_nombre:
            return by_nombre[nombre_ref]
        # fuzzy fallback
        best_p, best_s = None, 0.0
        for nombre, p in by_nombre.items():
            s = sim(nombre_ref, nombre)
            if s > best_s:
                best_s = s
                best_p = p
        return best_p if best_s >= THRESHOLD else None

    updated = skipped = no_proj = no_inv = 0
    issues = []

    for nombre_proy, nombre_cli, adm, cgm, rep in REFERENCIA:
        p = find_proyecto(nombre_proy)
        if not p:
            print(f"  NO-PROY   '{nombre_proy}'")
            no_proj += 1
            issues.append(f"Sin proyecto: {nombre_proy}")
            continue

        invs = p.get("inversionistas", [])
        result = best_inv(nombre_cli, invs)
        if not result:
            print(f"  NO-INV    '{p['nombre_comercial']}' / '{nombre_cli}'")
            no_inv += 1
            issues.append(f"Sin inversionista: {nombre_proy} / {nombre_cli}")
            continue

        inv, score = result
        payload = {}

        def needs(field, val):
            current = inv.get(field)
            return (current is None or FORCE) and val is not None

        if needs("tarifa_administracion", adm):
            payload["tarifa_administracion"] = adm
        if needs("tarifa_cgm", cgm):
            payload["tarifa_cgm"] = cgm
        if needs("tarifa_representacion", rep):
            payload["tarifa_representacion"] = rep

        if payload:
            print(f"  UPDATE  '{p['nombre_comercial']}' / '{inv['cliente_nombre']}'  (score: {score:.2f})")
            for k, v in payload.items():
                print(f"          {k}: {v}")
            if not DRY_RUN:
                patch_inversionista(p["id"], inv["id"], payload, headers)
            updated += 1
        else:
            print(f"  OK      '{p['nombre_comercial']}' / '{inv['cliente_nombre']}' — sin cambios")
            skipped += 1

    print(f"\n{tag}Resultado: {updated} actualizados, {skipped} sin cambios, {no_proj} sin proyecto, {no_inv} sin inversionista.")

    if issues:
        print(f"\nProblemas ({len(issues)}):")
        for i in issues:
            print(f"  - {i}")


if __name__ == "__main__":
    main()
