"""
Reconcilia proyecto_id en asic_solicitudes para los registros que quedaron sin match.
Usa el campo requerimiento_asic (ID del Excel) para cruzar con la planta del GESCON.xlsx
y aplicar el mapa manual confirmado de nombres similares.
"""
import os
import unicodedata, requests
import openpyxl

BASE_URL = "https://backend-production-63d8.up.railway.app/api/v1"
EMAIL = os.environ.get("ADMIN_USER", "juanjose@unergy.io")
PASSWORD = os.environ.get("ADMIN_PASS", "")
XLSX     = r"C:\Users\juan_\OneDrive\Documentos\Dev\cumplimiento\GESCON\GESCON.xlsx"

# Mapa manual: nombre GESCON (normalizado) → nombre_comercial en BD
MAPA_MANUAL = {
    "agustin 1":                       "GD Agustin 1",
    "complejo industrial cedillanos":  "Cedillanos",
    "gd biosolar generacion":          "GD Biosolar",
    "gd delta  2":                     "GD delta 2",
    "gd naos 3":                       "MGS Naos 3",
    "gd naos 2":                       "MGS Naos 2",   # alias en GESCON
    "granja solar uruaco":             "Minigranja Solar Uruaco",
    "mgs 0012 - la reserva":           "La Reserva",
    "mgs 0013 - la mesa":              "MGS 0013 La Mesa",
    "mgs 0016 - la puya":              "MGS 0016 - Puya",
    "mgs 0019 - el merengue":          "MGS 0019 El Merengue",
    "mgs 0021 - ibirico":              "MGS 0021 Ibirico",
    "mgs 0023 - el joropo":            "MGS 0023 Joropo",
    "mgs 0026 - valencia oriente":     "MGS 0026 Valencia Oriente 1",
    "mgs 0027 - valencia oriente 2":   "MGS 0027 Valencia Oriente 2",
    "mgs 0040 - la cacica":            "MGS 0040 Cacica",
    "mgs 0041 - las piloneras":        "MGS 0041 Piloneras",
    "minigranja solar canahuate":      "MGS 0005 Canahuate",
    "minigranja solar gandalf":        "MGS 0004 Valle de Gandalf",
    "minigranja 0009 la paz verso":    "MGS 0008 La Paz Verso",
    "minigranja 0017 - la paz esmeralda": "MGS 0017- Esmeralda",
    "minigranja 0018 - la paz leyenda":   "MGS 0018 La Paz Leyenda",
    "minigranja 005 - la paz vallenata":  "MGS 0007 La Paz Vallenata",
    "minigranja solar 0006- perija":   "MGS 0006 Perija",
    "minigranja solar 0009 - el molino": "MGS 0009 El Molino",
    "planta solar bayunca i":          "Bayunca",
    "sol&cielo 7 los bongos generacion": "Sol Y Cielo 7 Los Bongos",
    "sol&cielo 9 - cienaga generacion":  "Sol&Cielo 9 - Cienaga",
}


def norm(s):
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def login():
    r = requests.post(f"{BASE_URL}/auth/token",
                      data={"username": EMAIL, "password": PASSWORD},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def cargar_proyectos(h):
    page, items = 1, []
    while True:
        d = requests.get(f"{BASE_URL}/proyectos", params={"page": page, "size": 200}, headers=h, timeout=15).json()
        batch = d["items"] if isinstance(d, dict) else d
        if not batch: break
        items.extend(batch)
        if isinstance(d, dict) and len(items) >= d.get("total", 0): break
        page += 1
    return {norm(p["nombre_comercial"]): p["id"] for p in items}


def cargar_asic(h):
    # Trae todos los registros ASIC
    r = requests.get(f"{BASE_URL}/asic", headers=h, timeout=30)
    r.raise_for_status()
    return r.json()


def leer_mapa_xlsx():
    """Devuelve dict: requerimiento_asic → planta_nombre (primera planta)."""
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["GESCON"]
    mapa = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        id_ = row[0]
        planta = row[16]
        if id_ is None: continue
        req = str(int(float(id_)))
        if planta:
            primera = str(planta).split(",")[0].strip()
            mapa[req] = primera
    return mapa


def main():
    print("[1/5] Autenticando...")
    token = login()
    h = {"Authorization": f"Bearer {token}"}

    print("[2/5] Cargando proyectos...")
    proyectos_idx = cargar_proyectos(h)
    # Índice inverso: nombre_comercial (norm) → id  (ya lo tenemos)
    # Construir índice por nombre para búsqueda manual
    nombre_a_id = {norm(bd_name): pid for norm_key, pid in proyectos_idx.items()
                   for bd_name in [k for k, v in proyectos_idx.items() if v == pid]}
    # Mapa manual resuelto: norm(gescon) → proyecto_id
    mapa_resuelto = {}
    for gescon_norm, bd_name in MAPA_MANUAL.items():
        pid = proyectos_idx.get(norm(bd_name))
        if pid:
            mapa_resuelto[gescon_norm] = pid
        else:
            print(f"  [WARN] '{bd_name}' no encontrado en BD, se omite")

    print(f"      {len(mapa_resuelto)} entradas en mapa manual resuelto")

    print("[3/5] Leyendo GESCON.xlsx para mapa requerimiento→planta...")
    req_a_planta = leer_mapa_xlsx()

    print("[4/5] Cargando registros ASIC sin proyecto_id...")
    todos = cargar_asic(h)
    sin_proyecto = [r for r in todos if r.get("proyecto_id") is None]
    print(f"      {len(sin_proyecto)} registros sin proyecto_id")

    print("[5/5] Reconciliando...")
    ok = skip = err = 0
    for rec in sin_proyecto:
        req = rec.get("requerimiento_asic")
        if not req:
            skip += 1
            continue
        planta = req_a_planta.get(req)
        if not planta:
            skip += 1
            continue
        pid = mapa_resuelto.get(norm(planta))
        if not pid:
            print(f"  [SKIP] req={req} planta='{planta}' sin match en mapa")
            skip += 1
            continue

        resp = requests.patch(f"{BASE_URL}/asic/{rec['id']}", json={"proyecto_id": pid}, headers=h, timeout=15)
        if resp.ok:
            print(f"  [OK]   req={req} '{planta}' → proyecto_id={pid}")
            ok += 1
        else:
            print(f"  [ERR]  req={req} status={resp.status_code} {resp.text[:100]}")
            err += 1

    print(f"\n[DONE] OK={ok}  SKIP={skip}  ERR={err}")


if __name__ == "__main__":
    main()
