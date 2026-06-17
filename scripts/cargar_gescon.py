"""
Carga la hoja GESCON del archivo GESCON.xlsx en asic_solicitudes via API.
Uso: python scripts/cargar_gescon.py [--dry-run]
"""
import os
import sys, os, unicodedata
from datetime import datetime
import requests
import openpyxl

# ── Config ──────────────────────────────────────────────────────────────────
XLSX = r"C:\Users\juan_\OneDrive\Documentos\Dev\cumplimiento\GESCON\GESCON.xlsx"
BASE_URL = "https://backend-production-63d8.up.railway.app/api/v1"
EMAIL = os.environ.get("ADMIN_USER", "juanjose@unergy.io")
PASSWORD = os.environ.get("ADMIN_PASS", "")
DRY_RUN  = "--dry-run" in sys.argv

# ── Helpers ──────────────────────────────────────────────────────────────────

def norm(s):
    """Normaliza string: sin tildes, minúsculas, sin espacios extra."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()


TIPO_MAP = {
    "registro":      "registro",
    "modificacion":  "modificacion",
    "terminacion":   "terminacion",
    "desistimiento": "desistimiento",
}

ESTADO_MAP = {
    "publicado":   "publicado",
    "en proceso":  "en_proceso",
    "rechazado":   "rechazado",
    "desistido":   "desistido",
}


def map_tipo(v):
    return TIPO_MAP.get(norm(v or ""))


def map_estado(v):
    return ESTADO_MAP.get(norm(v or ""), "publicado")


def fecha(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    s = str(v).strip()[:10]
    return s if s else None


def sic_str(v):
    """Convierte el SIC numérico (88806.0) a string ('88806')."""
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


def primera_planta(v):
    """Si hay varias plantas separadas por coma, usa la primera."""
    if not v:
        return None
    return str(v).split(",")[0].strip()


# ── Autenticación ─────────────────────────────────────────────────────────────

def login():
    r = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


# ── Cargar proyectos para resolver nombres → IDs ──────────────────────────────

def cargar_proyectos(token):
    headers = {"Authorization": f"Bearer {token}"}
    page, items = 1, []
    while True:
        r = requests.get(f"{BASE_URL}/proyectos", params={"page": page, "size": 200}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        batch = data["items"] if isinstance(data, dict) else data
        if not batch:
            break
        items.extend(batch)
        if isinstance(data, dict) and len(items) >= data.get("total", 0):
            break
        page += 1
    # indice norm_nombre → id
    return {norm(p["nombre_comercial"]): p["id"] for p in items}


# ── Leer Excel ────────────────────────────────────────────────────────────────

def leer_gescon():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["GESCON"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    # Filtrar filas vacías (la hoja tiene muchas al final)
    return [r for r in rows if any(v is not None for v in r[:5])]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[1/4] Autenticando...")
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    print("[2/4] Cargando proyectos...")
    proyectos_idx = cargar_proyectos(token)
    print(f"      {len(proyectos_idx)} proyectos cargados")

    print("[3/4] Leyendo GESCON.xlsx...")
    filas = leer_gescon()
    print(f"      {len(filas)} filas a procesar")

    ok = err = skip = 0
    sin_proyecto = set()

    print("[4/4] Insertando en API...")
    for i, r in enumerate(filas):
        # Columnas: ID, Tipo, P.S, Contrato, Vendedor, Comprador,
        #           Nombre Contacto, Fecha Solicitud, Inicio, Final,
        #           Observaciones, Estado Solicitud, Tipo Mercado,
        #           Tipo Asignacion, % FNCER, Link, Planta asociada,
        #           Numero contrato, % despacho, Nombre interno
        (id_, tipo, ps, contrato, vendedor, comprador,
         contacto, fecha_sol, inicio, fin,
         obs, estado, tipo_merc, tipo_asign, pct_fncer,
         link, planta, num_contrato, pct_despacho, _nombre_int) = r[:20]

        tipo_mapped = map_tipo(tipo)
        if not tipo_mapped:
            print(f"  [SKIP] fila {i+2}: tipo desconocido '{tipo}'")
            skip += 1
            continue

        # Resolver proyecto_id (si hay varias plantas separadas por coma usa la primera)
        proyecto_id = None
        planta_lookup = primera_planta(planta)
        if planta_lookup:
            proyecto_id = proyectos_idx.get(norm(planta_lookup))
            if proyecto_id is None:
                sin_proyecto.add(str(planta_lookup))

        payload = {
            "requerimiento_asic": sic_str(id_),
            "tipo_solicitud": tipo_mapped,
            "prioridad_limitacion": int(ps) if ps is not None else None,
            "codigo_sic_contrato": sic_str(contrato),
            "codigo_sic_vendedor": str(vendedor).strip() if vendedor else None,
            "codigo_sic_comprador": str(comprador).strip() if comprador else None,
            "nombre_contacto_solicitante": str(contacto).strip() if contacto else None,
            "fecha_solicitud": fecha(fecha_sol),
            "fecha_inicio": fecha(inicio),
            "fecha_fin": fecha(fin),
            "observaciones": str(obs).strip() if obs else None,
            "estado_solicitud": map_estado(estado),
            "tipo_mercado": str(tipo_merc).strip() if tipo_merc else "No regulado",
            "tipo_asignacion": str(tipo_asign).strip() if tipo_asign else None,
            "porcentaje_fncer": safe_float(pct_fncer),
            "link_archivo": str(link).strip() if link else None,
            "porcentaje_despacho": safe_float(pct_despacho),
            "contrato_interno": str(num_contrato).strip() if num_contrato else None,
            "proyecto_id": proyecto_id,
        }

        if DRY_RUN:
            print(f"  [DRY] {payload['requerimiento_asic']} | {tipo_mapped} | {payload['codigo_sic_contrato']} | {planta}")
            ok += 1
            continue

        try:
            resp = requests.post(f"{BASE_URL}/asic", json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            ok += 1
            if (i + 1) % 100 == 0:
                print(f"  ... {i+1}/{len(filas)} procesadas")
        except Exception as e:
            body = ""
            try:
                body = resp.text[:200]
            except Exception:
                pass
            print(f"  [ERR] fila {i+2}: {e} | {body}")
            err += 1

    print()
    print(f"[DONE] OK={ok}  ERR={err}  SKIP={skip}")
    if sin_proyecto:
        print(f"\nPlantas sin match en proyectos ({len(sin_proyecto)}):")
        for p in sorted(sin_proyecto):
            print(f"  - {p}")


if __name__ == "__main__":
    main()
