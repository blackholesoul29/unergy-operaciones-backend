"""
Carga completa de proyectos operativos vía API REST:
  codigo_tsf, fecha_entrada_operacion, estado,
  srv_representacion, srv_cgm, srv_operacion.

"No Aplica" en codigo_tsf → no se toca.
Servicios vacíos (None) → no se modifican.

Uso:
    python scripts/cargar_operativos.py [--dry-run] [--force]

    --dry-run  muestra cambios sin escribir
    --force    sobreescribe aunque el campo ya tenga valor
"""
import sys
import unicodedata
from datetime import date
from difflib import SequenceMatcher

import requests

# ---------------------------------------------------------------------------
BASE = "https://backend-production-63d8.up.railway.app"
USER = "juanjose@unergy.io"
PASS = "Unergy2025!"
# ---------------------------------------------------------------------------

args = sys.argv[1:]
FORCE   = "--force"   in args
DRY_RUN = "--dry-run" in args

# ---------------------------------------------------------------------------
# Datos: (nombre_ref, codigo_tsf, fpo, representacion, cgm, operacion)
#   codigo_tsf  None = No Aplica → no se escribe
#   operacion   None = celda vacía → no se modifica
# ---------------------------------------------------------------------------
REFERENCIA = [
    # ── GDs / otros ─────────────────────────────────────────────────────────
    ("Parque solar GD-NAOS 1",                                        None,           date(2024,  8, 27), True,  True,  None),
    ("GD NAOS 2",                                                     None,           date(2025,  2, 27), True,  True,  None),
    ("Parque solar Marimonda",                                        None,           date(2025,  9, 11), True,  True,  None),
    ("Proyecto Bayunca I",                                            None,           date(2025,  6,  5), True,  False, None),
    ("GD NAOS 3",                                                     None,           date(2025,  4, 26), True,  True,  None),
    ("GD DELTA 1",                                                    None,           date(2025,  7, 15), True,  True,  None),
    ("GD POLARIS 1",                                                  None,           date(2025,  7, 30), True,  True,  None),
    ("Planta Solar Flotante Yurbaqua",                                None,           date(2025, 12, 21), True,  True,  None),
    ("GD SIRIUS",                                                     None,           date(2026,  1, 23), True,  True,  None),
    ("GD BIOSOLAR",                                                   None,           date(2026,  2, 18), True,  True,  None),
    ("GD ASTROLUMEN LA GARITA",                                       None,           date(2026,  2, 18), True,  True,  None),
    ("GD AGUSTÍN 1",                                                  None,           date(2025,  9, 23), True,  True,  None),
    ("GD 1MVA SAN ONOFRE",                                            None,           date(2025,  7, 13), True,  False, None),
    ("YUAN SOLAR",                                                    None,           date(2025, 12, 13), True,  True,  None),
    ("GD POLARIS 2",                                                  None,           date(2025,  9, 24), True,  True,  None),
    ("GD DELTA 2",                                                    None,           date(2025,  9, 19), True,  True,  None),
    ("Sol Y Cielo 7 Los Bongos",                                      None,           date(2026,  1,  1), True,  True,  None),
    ("CATEDRAL",                                                      None,           date(2026,  1, 29), True,  True,  None),
    ("GD SAN PELAYO",                                                 None,           date(2026,  3, 20), True,  True,  None),
    ("Granja 9 Cienaga",                                              None,           date(2026,  2, 19), True,  True,  None),
    # ── Minigranjas ─────────────────────────────────────────────────────────
    ("MiniGranja 0001 - Uruaco",                                      "COLATLT14P2",  date(2023,  7, 18), True,  True,  True),
    ("MiniGranja 0004 - Valle de Gandalf",                            "COLCEST61P3",  date(2024,  2, 22), True,  True,  True),
    ("MiniGranja 0005 - Cañahuate",                                   "COLCEST61P1",  date(2024,  2, 22), True,  True,  True),
    ("MiniGranja 0006 - Perijá (La inglesa)",                         "COLCEST58P2",  date(2024,  9, 16), True,  True,  True),
    ("MiniGranja 0007 - La Paz Vallenata (Medardo)",                  "COLCEST9P1",   date(2024,  8, 13), True,  True,  True),
    ("MiniGranja 0008 - La Paz Verso (Villa Sonia)",                  "COLCEST2P3",   date(2025,  1, 18), True,  True,  True),
    ("MiniGranja 0009 - El Molino (Macedonia)",                       "COLLAGT19P2",  date(2024,  9, 30), True,  True,  True),
    ("MiniGranja 0010 - Villanueva (los suspiros)",                   "COLLAGT27P2",  date(2025,  7, 25), True,  True,  True),
    ("MiniGranja 0013 - La Mesa (La Virginia 1)",                     "COLSANT10P1",  date(2025,  9, 12), True,  True,  True),
    ("MiniGranja 0014 - El Olimpo",                                   "COLSANT4P2",   date(2025,  7, 20), True,  True,  True),
    ("Minigranja 0016 - La Puya - Valledupar, Cesar (Jericó 4_Cesar)", "COLCEST45P5", date(2025, 4,  7), True,  True,  True),
    ("MiniGranja 0017 - La Paz Esmeralda - La Esmeralda 1",          "COLCEST17P1",  date(2025,  2, 26), True,  True,  True),
    ("Minigranja 0021 - Ibirico",                                     "COLCEST49P2",  date(2025,  7, 21), True,  True,  True),
    ("Minigranja 0040 - La Cacica",                                   "COLCEST55P1",  date(2026,  2, 28), True,  True,  True),
    ("Minigranja 0041  - Las piloneras",                              "COLCEST55P2",  date(2026,  2,  4), True,  True,  True),
    ("Minigranja 0075 - Chiriguaná Norte 2",                          "COLCEST60P4",  date(2026,  3, 12), True,  True,  True),
    ("Minigranja 0077 - Chiriguaná Norte 4",                          "COLCEST60P2",  date(2026,  3, 17), True,  True,  True),
    ("MiniGranja 0025 - El Copey Occidente",                          "COLCEST39P1",  date(2026,  3,  5), True,  True,  True),
    ("Minigranja 0018 - La Paz Leyenda",                              "COLCEST53P1",  date(2024, 12,  2), True,  True,  True),
    ("MiniGranja 0019 - El Merengue (Jericó 2_Cesar)",               "COLCEST45P7",  date(2025,  4, 16), True,  True,  True),
    ("Minigranja 0022 - La Cumbia",                                   "COLCEST45P4",  date(2026,  2,  5), True,  True,  True),
    ("MiniGranja 0024 - San Diego Sur",                               "COLCEST38P1",  date(2025, 12,  7), True,  True,  True),
    ("Minigranja 0026 - Valencia Oriente",                            "COLCEST74P1",  date(2026,  2, 13), True,  True,  True),
    ("Minigranja 0027 - Valencia Oriente 2",                          "COLCEST74P2",  date(2026,  2, 24), True,  True,  True),
    ("Minigranja 0015 - El Son",                                      "COLCEST45P1",  date(2025,  4, 28), True,  True,  True),
    ("Minigranja 0002 - Baraya",                                      "COLSUCT17P2",  date(2024,  2, 18), True,  True,  True),
    ("Minigranja 0012 - La Reserva",                                  "COLSANT9P1",   date(2025,  7,  4), True,  True,  True),
]

SIMILARITY_THRESHOLD = 0.60


def norm(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def best_match(ref_name: str, proyectos: list) -> tuple | None:
    best_p, best_score = None, 0.0
    for p in proyectos:
        s = similarity(ref_name, p["nombre_comercial"])
        if s > best_score:
            best_score = s
            best_p = p
    if best_score >= SIMILARITY_THRESHOLD:
        return best_p, best_score
    return None


def get_token() -> dict:
    r = requests.post(
        f"{BASE}/api/v1/auth/token",
        data={"username": USER, "password": PASS},
        timeout=30,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get_all_proyectos(headers: dict) -> list:
    r = requests.get(f"{BASE}/api/v1/proyectos?size=500", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["items"]


def patch_proyecto(pid: int, payload: dict, headers: dict):
    r = requests.patch(
        f"{BASE}/api/v1/proyectos/{pid}",
        json=payload,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def yn(v) -> str:
    if v is None:
        return "—"
    return "Sí" if v else "No"


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Cargando datos de proyectos operativos...\n")

    print("  Obteniendo token...", end=" ")
    headers = get_token()
    print("OK")

    print("  Cargando proyectos de la API...", end=" ")
    proyectos = get_all_proyectos(headers)
    print(f"{len(proyectos)} proyectos encontrados\n")

    updated = skipped = no_match = 0
    no_match_list = []

    for ref_name, tsf, fpo, rep, cgm, oper in REFERENCIA:
        result = best_match(ref_name, proyectos)
        if not result:
            print(f"  NO-MATCH  '{ref_name}'")
            no_match += 1
            no_match_list.append(ref_name)
            continue

        p, score = result
        payload = {}

        # codigo_tsf
        if tsf is not None:
            if not p.get("codigo_tsf") or FORCE:
                payload["codigo_tsf"] = tsf

        # fecha_entrada_operacion
        fpo_actual = p.get("fecha_entrada_operacion")
        if not fpo_actual or FORCE:
            payload["fecha_entrada_operacion"] = fpo.isoformat()

        # estado
        if p.get("estado") != "en_operacion":
            payload["estado"] = "en_operacion"

        # srv_representacion
        if not p.get("srv_representacion") or FORCE:
            payload["srv_representacion"] = rep

        # srv_cgm
        if not p.get("srv_cgm") or FORCE:
            payload["srv_cgm"] = cgm

        # srv_operacion
        if oper is not None and (not p.get("srv_operacion") or FORCE):
            payload["srv_operacion"] = oper

        if payload:
            print(f"  UPDATE  '{p['nombre_comercial']}'  (ref: '{ref_name}', score: {score:.2f})")
            for k, v in payload.items():
                print(f"          {k}: {v}")
            if not DRY_RUN:
                patch_proyecto(p["id"], payload, headers)
            updated += 1
        else:
            print(f"  OK      '{p['nombre_comercial']}'  (score: {score:.2f}) — sin cambios")
            skipped += 1

    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Resultado: {updated} actualizados, {skipped} sin cambios, {no_match} sin match.")

    if no_match_list:
        print(f"\nSin match ({len(no_match_list)}):")
        for n in no_match_list:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
