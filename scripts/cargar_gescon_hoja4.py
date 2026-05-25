"""
Carga la Hoja 4 de GESCON.xlsx (solicitudes antiguas) en asic_solicitudes.
Uso: python scripts/cargar_gescon_hoja4.py [--dry-run]
"""
import sys, unicodedata
from datetime import datetime
import requests
import openpyxl

XLSX = r"C:\Users\juan_\OneDrive\Documentos\Dev\cumplimiento\GESCON\GESCON.xlsx"
BASE_URL = "https://backend-production-63d8.up.railway.app/api/v1"
EMAIL    = "juanjose@unergy.io"
PASSWORD = "Unergy2025!"
DRY_RUN  = "--dry-run" in sys.argv

TIPO_MAP = {
    "registro": "registro",
    "modificacion": "modificacion",
    "terminacion": "terminacion",
    "desistimiento": "desistimiento",
}
ESTADO_MAP = {
    "publicado": "publicado",
    "en proceso": "en_proceso",
    "rechazado": "rechazado",
    "desistido": "desistido",
}


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip().lower()


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


def fecha(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    s = str(v).strip()[:10]
    return s if s else None


def login():
    r = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


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
    return {norm(p["nombre_comercial"]): p["id"] for p in items}


def main():
    print("[1/4] Autenticando...")
    token = login()
    headers = {"Authorization": f"Bearer {token}"}

    print("[2/4] Cargando proyectos...")
    proyectos_idx = cargar_proyectos(token)
    print(f"      {len(proyectos_idx)} proyectos")

    print("[3/4] Leyendo Hoja 4...")
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["Hoja 4"]
    # Cols: Requerimiento, Tipo, P.Lim, SIC Contrato, SIC Vendedor, SIC Comprador,
    #       Nombre Contacto, Fecha Solicitud, Fecha Inicio, Fecha Fin,
    #       Observaciones, Estado Solicitud, Tipo Mercado, Tipo Asignacion, % FNCER, Link, Planta asociada
    filas = [r for r in ws.iter_rows(min_row=2, values_only=True) if any(v is not None for v in r[:5])]
    print(f"      {len(filas)} filas")

    ok = err = skip = 0
    sin_proyecto = set()

    print("[4/4] Insertando...")
    for i, r in enumerate(filas):
        (req, tipo, ps, sic_cont, sic_vend, sic_comp,
         contacto, fecha_sol, f_inicio, f_fin,
         obs, estado, tipo_merc, tipo_asign, pct_fncer,
         link, planta) = (list(r) + [None]*17)[:17]

        tipo_mapped = TIPO_MAP.get(norm(tipo))
        if not tipo_mapped:
            print(f"  [SKIP] fila {i+2}: tipo desconocido '{tipo}'")
            skip += 1
            continue

        proyecto_id = None
        if planta:
            proyecto_id = proyectos_idx.get(norm(str(planta).split(",")[0].strip()))
            if proyecto_id is None:
                sin_proyecto.add(str(planta).split(",")[0].strip())

        payload = {
            "requerimiento_asic": sic_str(req),
            "tipo_solicitud": tipo_mapped,
            "prioridad_limitacion": int(ps) if ps is not None else None,
            "codigo_sic_contrato": sic_str(sic_cont),
            "codigo_sic_vendedor": str(sic_vend).strip() if sic_vend else None,
            "codigo_sic_comprador": str(sic_comp).strip() if sic_comp else None,
            "nombre_contacto_solicitante": str(contacto).strip() if contacto else None,
            "fecha_solicitud": fecha(fecha_sol),
            "fecha_inicio": fecha(f_inicio),
            "fecha_fin": fecha(f_fin),
            "observaciones": str(obs).strip() if obs else None,
            "estado_solicitud": ESTADO_MAP.get(norm(estado), "en_proceso"),
            "tipo_mercado": str(tipo_merc).strip() if tipo_merc else "No regulado",
            "tipo_asignacion": str(tipo_asign).strip() if tipo_asign else None,
            "porcentaje_fncer": safe_float(pct_fncer),
            "link_archivo": str(link).strip() if link else None,
            "proyecto_id": proyecto_id,
        }

        if DRY_RUN:
            print(f"  [DRY] {payload['requerimiento_asic']} | {tipo_mapped} | {planta}")
            ok += 1
            continue

        try:
            resp = requests.post(f"{BASE_URL}/asic", json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            ok += 1
        except Exception as e:
            body = ""
            try:
                body = resp.text[:200]
            except Exception:
                pass
            print(f"  [ERR] fila {i+2}: {e} | {body}")
            err += 1

    print(f"\n[DONE] OK={ok}  ERR={err}  SKIP={skip}")
    if sin_proyecto:
        print(f"\nPlantas sin match ({len(sin_proyecto)}):")
        for p in sorted(sin_proyecto):
            print(f"  - {p}")


if __name__ == "__main__":
    main()
