"""
Carga completa de proyectos operativos vía API REST:
  codigo_tsf, fecha_entrada_operacion, estado,
  srv_representacion, srv_cgm, srv_operacion.

Usa topic_slug como clave de lookup (exacto, sin ambigüedad).
"No Aplica" en codigo_tsf → no se toca.
Servicios vacíos (None) → no se modifican.

Uso:
    python scripts/cargar_operativos.py [--dry-run] [--force]
"""
import sys
from datetime import date
import requests

BASE = "https://backend-production-63d8.up.railway.app"
from _creds import api_credentials

USER, PASS = api_credentials()

args = sys.argv[1:]
FORCE   = "--force"   in args
DRY_RUN = "--dry-run" in args

# ---------------------------------------------------------------------------
# Datos: (topic_slug, nombre_ref, codigo_tsf, fpo, representacion, cgm, operacion)
#   codigo_tsf  None = No Aplica → no se escribe
#   operacion   None = celda vacía → no se modifica
# ---------------------------------------------------------------------------
REFERENCIA = [
    # ── GDs / otros ─────────────────────────────────────────────────────────
    ("naos1",              "Parque solar GD-NAOS 1",              None,           date(2024,  8, 27), True,  True,  None),
    ("naos2",              "GD NAOS 2",                           None,           date(2025,  2, 27), True,  True,  None),
    ("marimonda",          "Parque solar Marimonda",              None,           date(2025,  9, 11), True,  True,  None),
    ("bayunca",            "Proyecto Bayunca I",                  None,           date(2025,  6,  5), True,  False, None),
    ("naos3",              "GD NAOS 3",                           None,           date(2025,  4, 26), True,  True,  None),
    ("delta_1",            "GD DELTA 1",                          None,           date(2025,  7, 15), True,  True,  None),
    ("polaris_1",          "GD POLARIS 1",                        None,           date(2025,  7, 30), True,  True,  None),
    ("yurbaqua",           "Planta Solar Flotante Yurbaqua",      None,           date(2025, 12, 21), True,  True,  None),
    ("sirius",             "GD SIRIUS",                           None,           date(2026,  1, 23), True,  True,  None),
    ("biosolar",           "GD BIOSOLAR",                         None,           date(2026,  2, 18), True,  True,  None),
    ("astrolumen",         "GD ASTROLUMEN LA GARITA",             None,           date(2026,  2, 18), True,  True,  None),
    ("agustin_1",          "GD AGUSTÍN 1",                        None,           date(2025,  9, 23), True,  True,  None),
    ("san_onofre",         "GD 1MVA SAN ONOFRE",                  None,           date(2025,  7, 13), True,  False, None),
    ("yuan_solar",         "YUAN SOLAR",                          None,           date(2025, 12, 13), True,  True,  None),
    ("polaris_2",          "GD POLARIS 2",                        None,           date(2025,  9, 24), True,  True,  None),
    ("delta_2",            "GD DELTA 2",                          None,           date(2025,  9, 19), True,  True,  None),
    ("bongos",             "Sol Y Cielo 7 Los Bongos",            None,           date(2026,  1,  1), True,  True,  None),
    ("catedral",           "CATEDRAL",                            None,           date(2026,  1, 29), True,  True,  None),
    ("san_pelayo",         "GD SAN PELAYO",                       None,           date(2026,  3, 20), True,  True,  None),
    ("cienaga",            "Granja 9 Cienaga",                    None,           date(2026,  2, 19), True,  True,  None),
    # ── Minigranjas ─────────────────────────────────────────────────────────
    ("uruaco_gd",          "MiniGranja 0001 - Uruaco",            "COLATLT14P2",  date(2023,  7, 18), True,  True,  True),
    ("gandalf",            "MiniGranja 0004 - Valle de Gandalf",  "COLCEST61P3",  date(2024,  2, 22), True,  True,  True),
    ("canahuate",          "MiniGranja 0005 - Cañahuate",         "COLCEST61P1",  date(2024,  2, 22), True,  True,  True),
    ("perija",             "MiniGranja 0006 - Perijá",            "COLCEST58P2",  date(2024,  9, 16), True,  True,  True),
    ("vallenata",          "MiniGranja 0007 - La Paz Vallenata",  "COLCEST9P1",   date(2024,  8, 13), True,  True,  True),
    ("verso",              "MiniGranja 0008 - La Paz Verso",      "COLCEST2P3",   date(2025,  1, 18), True,  True,  True),
    ("elmolino",           "MiniGranja 0009 - El Molino",         "COLLAGT19P2",  date(2024,  9, 30), True,  True,  True),
    ("villanueva",         "MiniGranja 0010 - Villanueva",        "COLLAGT27P2",  date(2025,  7, 25), True,  True,  True),
    ("lamesa",             "MiniGranja 0013 - La Mesa",           "COLSANT10P1",  date(2025,  9, 12), True,  True,  True),
    ("olimpo",             "MiniGranja 0014 - El Olimpo",         "COLSANT4P2",   date(2025,  7, 20), True,  True,  True),
    ("puya",               "Minigranja 0016 - La Puya",           "COLCEST45P5",  date(2025,  4,  7), True,  True,  True),
    ("esmeralda",          "MiniGranja 0017 - La Paz Esmeralda",  "COLCEST17P1",  date(2025,  2, 26), True,  True,  True),
    ("ibirico",            "Minigranja 0021 - Ibirico",           "COLCEST49P2",  date(2025,  7, 21), True,  True,  True),
    ("cacica",             "Minigranja 0040 - La Cacica",         "COLCEST55P1",  date(2026,  2, 28), True,  True,  True),
    ("piloneras",          "Minigranja 0041 - Las piloneras",     "COLCEST55P2",  date(2026,  2,  4), True,  True,  True),
    ("chiriguana_norte_2", "Minigranja 0075 - Chiriguaná Norte 2","COLCEST60P4",  date(2026,  3, 12), True,  True,  True),
    ("chiriguana_norte_4", "Minigranja 0077 - Chiriguaná Norte 4","COLCEST60P2",  date(2026,  3, 17), True,  True,  True),
    ("copey_occidente",    "MiniGranja 0025 - El Copey Occidente","COLCEST39P1",  date(2026,  3,  5), True,  True,  True),
    ("mgs18",              "Minigranja 0018 - La Paz Leyenda",    "COLCEST53P1",  date(2024, 12,  2), True,  True,  True),
    ("jerico_merengue",    "MiniGranja 0019 - El Merengue",       "COLCEST45P7",  date(2025,  4, 16), True,  True,  True),
    ("cumbia",             "Minigranja 0022 - La Cumbia",         "COLCEST45P4",  date(2026,  2,  5), True,  True,  True),
    ("san_diego_sur",      "MiniGranja 0024 - San Diego Sur",     "COLCEST38P1",  date(2025, 12,  7), True,  True,  True),
    ("valenciaoriente",    "Minigranja 0026 - Valencia Oriente",  "COLCEST74P1",  date(2026,  2, 13), True,  True,  True),
    ("valencia_oriente_2", "Minigranja 0027 - Valencia Oriente 2","COLCEST74P2",  date(2026,  2, 24), True,  True,  True),
    ("jerico_el_son",      "Minigranja 0015 - El Son",            "COLCEST45P1",  date(2025,  4, 28), True,  True,  True),
    ("baraya",             "Minigranja 0002 - Baraya",            "COLSUCT17P2",  date(2024,  2, 18), True,  True,  True),
    ("mgs0012lareserva",   "Minigranja 0012 - La Reserva",        "COLSANT9P1",   date(2025,  7,  4), True,  True,  True),
]


def get_token() -> dict:
    r = requests.post(f"{BASE}/api/v1/auth/token",
                      data={"username": USER, "password": PASS}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_all_proyectos(headers: dict) -> dict:
    r = requests.get(f"{BASE}/api/v1/proyectos?size=500", headers=headers, timeout=30)
    r.raise_for_status()
    return {p["topic_slug"]: p for p in r.json()["items"] if p.get("topic_slug")}


def patch_proyecto(pid: int, payload: dict, headers: dict):
    r = requests.patch(f"{BASE}/api/v1/proyectos/{pid}",
                       json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def yn(v) -> str:
    return "—" if v is None else ("Sí" if v else "No")


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Cargando datos de proyectos operativos...\n")

    print("  Autenticando...", end=" ", flush=True)
    headers = get_token()
    print("OK")

    print("  Cargando proyectos...", end=" ", flush=True)
    by_slug = get_all_proyectos(headers)
    print(f"{len(by_slug)} proyectos con topic_slug\n")

    updated = skipped = no_match = 0
    no_match_list = []

    for slug, nombre_ref, tsf, fpo, rep, cgm, oper in REFERENCIA:
        p = by_slug.get(slug)
        if not p:
            print(f"  NO-MATCH  slug='{slug}'  ('{nombre_ref}')")
            no_match += 1
            no_match_list.append(f"{slug} / {nombre_ref}")
            continue

        payload = {}

        if tsf is not None and (not p.get("codigo_tsf") or FORCE):
            payload["codigo_tsf"] = tsf

        if not p.get("fecha_entrada_operacion") or FORCE:
            payload["fecha_entrada_operacion"] = fpo.isoformat()

        if p.get("estado") != "en_operacion":
            payload["estado"] = "en_operacion"

        if not p.get("srv_representacion") or FORCE:
            payload["srv_representacion"] = rep

        if p.get("srv_cgm") != cgm and (not p.get("srv_cgm") or FORCE):
            payload["srv_cgm"] = cgm

        if oper is not None and (not p.get("srv_operacion") or FORCE):
            payload["srv_operacion"] = oper

        if payload:
            print(f"  UPDATE  '{p['nombre_comercial']}'  [{slug}]")
            for k, v in payload.items():
                print(f"          {k}: {v}")
            if not DRY_RUN:
                patch_proyecto(p["id"], payload, headers)
            updated += 1
        else:
            print(f"  OK      '{p['nombre_comercial']}'  [{slug}] — sin cambios")
            skipped += 1

    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Resultado: {updated} actualizados, {skipped} sin cambios, {no_match} sin match.")

    if no_match_list:
        print(f"\nSin match ({len(no_match_list)}):")
        for n in no_match_list:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
