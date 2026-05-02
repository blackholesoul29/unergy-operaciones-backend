"""
Carga el contrato PPA Terpel 1 (UNERGY 001-2023) en producción.

Uso:
  python scripts/cargar_terpel1.py --listar          # ver proyectos disponibles
  python scripts/cargar_terpel1.py --ids 1,2,3,...   # crear contrato con esos IDs
  python scripts/cargar_terpel1.py --ids 1,2,3,... --dry-run  # simular sin guardar
"""

import sys
import argparse
import requests

BASE_URL = "https://backend-production-63d8.up.railway.app"
EMAIL    = "juanjose@unergy.io"
PASSWORD = "Unergy2025!"

MESES = {
    "Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,
    "Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12
}

# ── Datos cabecera ─────────────────────────────────────────────────────────────
CONTRATO = {
    "numero_codigo_contrato": "UNERGY 001-2023",
    "nombre_interno":         "Terpel 1",
    "comprador_nombre":       "TERPEL ENERGÍA S.A.S. E.S.P.",
    "comprador_nit":          "900433032-9",
    "vendedor_nombre":        "UNERGY ENERGÍA DIGITAL SAS ESP",
    "vendedor_nit":           "901497656-2",
    "fecha_inicio":           "2023-11-23",
    "fecha_fin":              "2039-12-31",
    "indice_indexacion":      "IPP",
    "periodicidad_indexacion":"mensual",
    "periodo_indexacion_base":"2023-07",
    "valor_indexacion_base":  173.52,
    "periodicidad_facturacion":"mensual",
    "tiempo_pago":            15,
}

# ── Tabla de tarifas (COP/kWh) ─────────────────────────────────────────────────
TARIFAS_RAW = """
2023,Noviembre,460
2023,Diciembre,460
2024,Enero,460
2024,Febrero,460
2024,Marzo,460
2024,Abril,460
2024,Mayo,460
2024,Junio,460
2024,Julio,460
2024,Agosto,460
2024,Septiembre,460
2024,Octubre,460
2024,Noviembre,460
2024,Diciembre,460
2025,Enero,380
2025,Febrero,380
2025,Marzo,380
2025,Abril,380
2025,Mayo,380
2025,Junio,380
2025,Julio,380
2025,Agosto,380
2025,Septiembre,380
2025,Octubre,380
2025,Noviembre,380
2025,Diciembre,380
2026,Enero,340
2026,Febrero,340
2026,Marzo,340
2026,Abril,340
2026,Mayo,340
2026,Junio,340
2026,Julio,340
2026,Agosto,340
2026,Septiembre,340
2026,Octubre,340
2026,Noviembre,340
2026,Diciembre,340
2027,Enero,319
2027,Febrero,319
2027,Marzo,319
2027,Abril,319
2027,Mayo,319
2027,Junio,319
2027,Julio,319
2027,Agosto,319
2027,Septiembre,319
2027,Octubre,319
2027,Noviembre,319
2027,Diciembre,319
2028,Enero,274
2028,Febrero,274
2028,Marzo,274
2028,Abril,274
2028,Mayo,274
2028,Junio,274
2028,Julio,274
2028,Agosto,274
2028,Septiembre,274
2028,Octubre,274
2028,Noviembre,274
2028,Diciembre,274
2029,Enero,273
2029,Febrero,273
2029,Marzo,273
2029,Abril,273
2029,Mayo,273
2029,Junio,273
2029,Julio,273
2029,Agosto,273
2029,Septiembre,273
2029,Octubre,273
2029,Noviembre,273
2029,Diciembre,273
2030,Enero,273
2030,Febrero,273
2030,Marzo,273
2030,Abril,273
2030,Mayo,273
2030,Junio,273
2030,Julio,273
2030,Agosto,273
2030,Septiembre,273
2030,Octubre,273
2030,Noviembre,273
2030,Diciembre,273
2031,Enero,263
2031,Febrero,263
2031,Marzo,263
2031,Abril,263
2031,Mayo,263
2031,Junio,263
2031,Julio,263
2031,Agosto,263
2031,Septiembre,263
2031,Octubre,263
2031,Noviembre,263
2031,Diciembre,263
2032,Enero,260
2032,Febrero,260
2032,Marzo,260
2032,Abril,260
2032,Mayo,260
2032,Junio,260
2032,Julio,260
2032,Agosto,260
2032,Septiembre,260
2032,Octubre,260
2032,Noviembre,260
2032,Diciembre,260
2033,Enero,260
2033,Febrero,260
2033,Marzo,260
2033,Abril,260
2033,Mayo,260
2033,Junio,260
2033,Julio,260
2033,Agosto,260
2033,Septiembre,260
2033,Octubre,260
2033,Noviembre,260
2033,Diciembre,260
2034,Enero,256
2034,Febrero,256
2034,Marzo,256
2034,Abril,256
2034,Mayo,256
2034,Junio,256
2034,Julio,256
2034,Agosto,256
2034,Septiembre,256
2034,Octubre,256
2034,Noviembre,256
2034,Diciembre,256
2035,Enero,255
2035,Febrero,255
2035,Marzo,255
2035,Abril,255
2035,Mayo,255
2035,Junio,255
2035,Julio,255
2035,Agosto,255
2035,Septiembre,255
2035,Octubre,255
2035,Noviembre,255
2035,Diciembre,255
2036,Enero,254
2036,Febrero,254
2036,Marzo,254
2036,Abril,254
2036,Mayo,254
2036,Junio,254
2036,Julio,254
2036,Agosto,254
2036,Septiembre,254
2036,Octubre,254
2036,Noviembre,254
2036,Diciembre,254
2037,Enero,253
2037,Febrero,253
2037,Marzo,253
2037,Abril,253
2037,Mayo,253
2037,Junio,253
2037,Julio,253
2037,Agosto,253
2037,Septiembre,253
2037,Octubre,253
2037,Noviembre,253
2037,Diciembre,253
2038,Enero,252
2038,Febrero,252
2038,Marzo,252
2038,Abril,252
2038,Mayo,252
2038,Junio,252
2038,Julio,252
2038,Agosto,252
2038,Septiembre,252
2038,Octubre,252
2038,Noviembre,252
2038,Diciembre,252
2039,Enero,252
2039,Febrero,252
2039,Marzo,252
2039,Abril,252
2039,Mayo,252
2039,Junio,252
2039,Julio,252
2039,Agosto,252
2039,Septiembre,252
2039,Octubre,252
2039,Noviembre,252
2039,Diciembre,252
""".strip()

# ── Tabla de compromisos energía (MWh/mes) ─────────────────────────────────────
ENERGIA_RAW = """
2023,Noviembre,90,180
2023,Diciembre,90,180
2024,Enero,100,180
2024,Febrero,200,360
2024,Marzo,200,360
2024,Abril,200,360
2024,Mayo,400,720
2024,Junio,500,900
2024,Julio,550,900
2024,Agosto,770,1260
2024,Septiembre,770,1260
2024,Octubre,990,1620
2024,Noviembre,990,1620
2024,Diciembre,1100,1800
2025,Enero,1327,2171
2025,Febrero,1198,1961
2025,Marzo,1327,2171
2025,Abril,1284,2101
2025,Mayo,1327,2171
2025,Junio,1284,2101
2025,Julio,1327,2171
2025,Agosto,1327,2171
2025,Septiembre,1284,2101
2025,Octubre,1327,2171
2025,Noviembre,1284,2101
2025,Diciembre,1327,2171
2026,Enero,1345,2201
2026,Febrero,1215,1988
2026,Marzo,1345,2201
2026,Abril,1302,2130
2026,Mayo,1345,2201
2026,Junio,1302,2130
2026,Julio,1345,2201
2026,Agosto,1345,2201
2026,Septiembre,1302,2130
2026,Octubre,1345,2201
2026,Noviembre,1302,2130
2026,Diciembre,1345,2201
2027,Enero,1345,2201
2027,Febrero,1215,1988
2027,Marzo,1345,2201
2027,Abril,1302,2130
2027,Mayo,1345,2201
2027,Junio,1302,2130
2027,Julio,1345,2201
2027,Agosto,1345,2201
2027,Septiembre,1302,2130
2027,Octubre,1345,2201
2027,Noviembre,1302,2130
2027,Diciembre,1345,2201
2028,Enero,1342,2195
2028,Febrero,1255,2054
2028,Marzo,1342,2195
2028,Abril,1298,2125
2028,Mayo,1342,2195
2028,Junio,1298,2125
2028,Julio,1342,2195
2028,Agosto,1342,2195
2028,Septiembre,1298,2125
2028,Octubre,1342,2195
2028,Noviembre,1298,2125
2028,Diciembre,1342,2195
2029,Enero,1345,2201
2029,Febrero,1215,1988
2029,Marzo,1345,2201
2029,Abril,1302,2130
2029,Mayo,1345,2201
2029,Junio,1302,2130
2029,Julio,1345,2201
2029,Agosto,1345,2201
2029,Septiembre,1302,2130
2029,Octubre,1345,2201
2029,Noviembre,1302,2130
2029,Diciembre,1345,2201
2030,Enero,1345,2201
2030,Febrero,1215,1988
2030,Marzo,1345,2201
2030,Abril,1302,2130
2030,Mayo,1345,2201
2030,Junio,1302,2130
2030,Julio,1345,2201
2030,Agosto,1345,2201
2030,Septiembre,1302,2130
2030,Octubre,1345,2201
2030,Noviembre,1302,2130
2030,Diciembre,1345,2201
2031,Enero,1345,2201
2031,Febrero,1215,1988
2031,Marzo,1345,2201
2031,Abril,1302,2130
2031,Mayo,1345,2201
2031,Junio,1302,2130
2031,Julio,1345,2201
2031,Agosto,1345,2201
2031,Septiembre,1302,2130
2031,Octubre,1345,2201
2031,Noviembre,1302,2130
2031,Diciembre,1345,2201
2032,Enero,1342,2195
2032,Febrero,1255,2054
2032,Marzo,1342,2195
2032,Abril,1298,2125
2032,Mayo,1342,2195
2032,Junio,1298,2125
2032,Julio,1342,2195
2032,Agosto,1342,2195
2032,Septiembre,1298,2125
2032,Octubre,1342,2195
2032,Noviembre,1298,2125
2032,Diciembre,1342,2195
2033,Enero,1345,2201
2033,Febrero,1215,1988
2033,Marzo,1345,2201
2033,Abril,1302,2130
2033,Mayo,1345,2201
2033,Junio,1302,2130
2033,Julio,1345,2201
2033,Agosto,1345,2201
2033,Septiembre,1302,2130
2033,Octubre,1345,2201
2033,Noviembre,1302,2130
2033,Diciembre,1345,2201
2034,Enero,1345,2201
2034,Febrero,1215,1988
2034,Marzo,1345,2201
2034,Abril,1302,2130
2034,Mayo,1345,2201
2034,Junio,1302,2130
2034,Julio,1345,2201
2034,Agosto,1345,2201
2034,Septiembre,1302,2130
2034,Octubre,1345,2201
2034,Noviembre,1302,2130
2034,Diciembre,1345,2201
2035,Enero,1345,2201
2035,Febrero,1215,1988
2035,Marzo,1345,2201
2035,Abril,1302,2130
2035,Mayo,1345,2201
2035,Junio,1302,2130
2035,Julio,1345,2201
2035,Agosto,1345,2201
2035,Septiembre,1302,2130
2035,Octubre,1345,2201
2035,Noviembre,1302,2130
2035,Diciembre,1345,2201
2036,Enero,1342,2195
2036,Febrero,1255,2054
2036,Marzo,1342,2195
2036,Abril,1298,2125
2036,Mayo,1342,2195
2036,Junio,1298,2125
2036,Julio,1342,2195
2036,Agosto,1342,2195
2036,Septiembre,1298,2125
2036,Octubre,1342,2195
2036,Noviembre,1298,2125
2036,Diciembre,1342,2195
2037,Enero,1345,2201
2037,Febrero,1215,1988
2037,Marzo,1345,2201
2037,Abril,1302,2130
2037,Mayo,1345,2201
2037,Junio,1302,2130
2037,Julio,1345,2201
2037,Agosto,1345,2201
2037,Septiembre,1302,2130
2037,Octubre,1345,2201
2037,Noviembre,1302,2130
2037,Diciembre,1345,2201
2038,Enero,1345,2201
2038,Febrero,1215,1988
2038,Marzo,1345,2201
2038,Abril,1302,2130
2038,Mayo,1345,2201
2038,Junio,1302,2130
2038,Julio,1345,2201
2038,Agosto,1345,2201
2038,Septiembre,1302,2130
2038,Octubre,1345,2201
2038,Noviembre,1302,2130
2038,Diciembre,1345,2201
2039,Enero,1345,2201
2039,Febrero,1215,1988
2039,Marzo,1345,2201
2039,Abril,1302,2130
2039,Mayo,1345,2201
2039,Junio,1302,2130
2039,Julio,1345,2201
2039,Agosto,1345,2201
2039,Septiembre,1302,2130
2039,Octubre,1345,2201
2039,Noviembre,1302,2130
2039,Diciembre,1345,2201
""".strip()


def parse_tarifas():
    rows = []
    for line in TARIFAS_RAW.splitlines():
        año, mes_str, tarifa = line.split(",")
        rows.append({"año": int(año), "mes": MESES[mes_str.strip()], "tarifa": float(tarifa)})
    return rows


def parse_energia():
    rows = []
    for line in ENERGIA_RAW.splitlines():
        año, mes_str, emin, emax = line.split(",")
        rows.append({
            "año": int(año),
            "mes": MESES[mes_str.strip()],
            "energia_minima": float(emin),
            "energia_maxima": float(emax),
        })
    return rows


def login(s: requests.Session) -> str:
    r = s.post(f"{BASE_URL}/api/v1/auth/token",
               data={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"
    print(f"✓ Login como {EMAIL}")
    return token


def listar_proyectos(s: requests.Session):
    r = s.get(f"{BASE_URL}/api/v1/proyectos?limit=200")
    r.raise_for_status()
    proyectos = r.json()
    print(f"\n{'ID':>5}  {'Nombre comercial':<50}  {'Operador'}")
    print("-" * 80)
    for p in sorted(proyectos, key=lambda x: x.get("nombre_comercial","") or ""):
        print(f"{p['id']:>5}  {(p.get('nombre_comercial') or ''):<50}  {p.get('operador_red') or ''}")
    print(f"\nTotal: {len(proyectos)} proyectos")


def crear_contrato(s: requests.Session, proyecto_ids: list[int], dry_run: bool):
    payload = {**CONTRATO, "proyecto_ids": proyecto_ids}

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Creando contrato '{payload['nombre_interno']}'...")
    print(f"  Proyectos: {proyecto_ids}")
    print(f"  Período: {payload['fecha_inicio']} → {payload['fecha_fin']}")

    if dry_run:
        print("  [DRY-RUN] No se envía nada al servidor.")
        return None

    r = s.post(f"{BASE_URL}/api/v1/ppa", json=payload)
    if not r.ok:
        print(f"✗ Error creando contrato: {r.status_code} {r.text}")
        sys.exit(1)

    contrato = r.json()
    cid = contrato["id"]
    print(f"✓ Contrato creado — ID: {cid}")
    return cid


def cargar_tarifas(s: requests.Session, cid: int, dry_run: bool):
    rows = parse_tarifas()
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Cargando {len(rows)} filas de tarifas...")

    if dry_run:
        print(f"  Primera: {rows[0]}  Última: {rows[-1]}")
        return

    r = s.put(f"{BASE_URL}/api/v1/ppa/{cid}/tarifas", json=rows)
    if not r.ok:
        print(f"✗ Error cargando tarifas: {r.status_code} {r.text}")
        sys.exit(1)
    print(f"✓ {len(r.json())} tarifas guardadas")


def cargar_energia(s: requests.Session, cid: int, dry_run: bool):
    rows = parse_energia()
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Cargando {len(rows)} filas de energía...")

    if dry_run:
        print(f"  Primera: {rows[0]}  Última: {rows[-1]}")
        return

    r = s.put(f"{BASE_URL}/api/v1/ppa/{cid}/compromisos", json=rows)
    if not r.ok:
        print(f"✗ Error cargando energía: {r.status_code} {r.text}")
        sys.exit(1)
    print(f"✓ {len(r.json())} compromisos de energía guardados")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listar",  action="store_true", help="Listar proyectos disponibles")
    parser.add_argument("--ids",     type=str,            help="IDs de proyectos separados por coma, ej: 1,2,3")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin guardar nada")
    args = parser.parse_args()

    s = requests.Session()
    login(s)

    if args.listar:
        listar_proyectos(s)
        return

    if not args.ids:
        print("Usa --listar para ver proyectos, luego --ids para crear el contrato.")
        print("Ejemplo: python scripts/cargar_terpel1.py --ids 5,8,12,15,20,21,22,25,30,31,32,35")
        sys.exit(1)

    proyecto_ids = [int(x.strip()) for x in args.ids.split(",")]
    if len(proyecto_ids) != 12:
        print(f"⚠ Se esperan 12 IDs, recibí {len(proyecto_ids)}: {proyecto_ids}")
        confirm = input("¿Continuar de todas formas? (s/N): ")
        if confirm.lower() != "s":
            sys.exit(0)

    cid = crear_contrato(s, proyecto_ids, args.dry_run)
    if cid:
        cargar_tarifas(s, cid, args.dry_run)
        cargar_energia(s, cid, args.dry_run)
        print(f"\n✅ Contrato Terpel 1 registrado completo (ID: {cid})")
        print(f"   Ver en: https://frontend-taupe-six-252g9aw47x.vercel.app/servicios")


if __name__ == "__main__":
    main()
