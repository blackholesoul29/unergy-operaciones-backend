#!/usr/bin/env python3
"""
Carga datos de autoconsumo 2026 (Excel Panel Seguimiento Contable) al sistema
de liquidaciones vía API REST.

Columnas del Excel (0-based):
  A=0  Proyecto
  B=1  CLIENTE
  C=2  Inversionista
  D=3  Documento contable   ← solo "Mandato"
  E=4  Ciudad
  F=5  Concepto
  G=6  Total
  H=7  Factura (NroFactura)
  I=8  Link Carpeta General
  J=9  Codigo

Uso:
  python scripts/cargar_autoconsumo_csv.py \
      --xlsx data/2026_Autoconsumo_Panel_Seguimiento_Contable.xlsx \
      --hojas Enero Febrero Marzo Abril \
      --usuario jessica@unergy.io \
      --password Unergy2025! \
      --limpiar
"""
import argparse
import io
import re
import sys
import unicodedata

# Forzar stdout UTF-8 en Windows (evita UnicodeEncodeError con caracteres especiales)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from openpyxl import load_workbook
import requests

# ── Mapa mes → número ─────────────────────────────────────────────────────────
MESES_MAP = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}

# ── Mapa concepto → tipo_linea ────────────────────────────────────────────────
TIPO_LINEA_MAP = [
    (r"ingreso bruto|^ingreso$",              "ingreso_bruto"),
    (r"despacho",                             "despacho"),
    (r"ventas en bolsa",                      "ventas_en_bolsa"),
    (r"compras en bolsa|compras a ",          "compras_en_bolsa"),
    (r"redistribuci",                         "redistribucion_ingresos"),
    (r"comercializaci",                       "ajuste_comercializacion"),
    (r"ajuste.*xm|xm.*ajuste",               "ajuste_xm"),
    (r"ajuste.*unergy",                       "ajuste_unergy"),
    (r"ajuste.*administr",                    "otro_costo"),
    (r"arriendo",                             "arriendo"),
    (r"mantenimiento",                        "mantenimiento"),
    (r"iva.*internet|internet.*iva",          "iva_internet"),
    (r"internet",                             "servicio_internet"),
    (r"poliza.*cumplimiento|p.liza.*cumpl",   "poliza_cumplimiento"),
    (r"poliza|incendio|lucro cesante",        "seguro"),
    (r"servicios p.blicos|consumo de energ",  "servicios_publicos_consumo"),
    (r"cambio.*equipo|equipo.*medida",        "cambio_equipos_medida"),
    (r"representaci",                         "representacion"),
    (r"^cgm",                                 "cgm"),
    (r"administraci|valor final",             "administracion"),
    (r"reteica",                              "reteica"),
    (r"ica opex",                             "ica_opex"),
    (r"iva|i\.v\.a",                          "iva"),
    (r"retenci",                              "retencion_fuente"),
    (r"porcentaje.*participaci",              "porcentaje_participacion"),
    (r"interes",                              "intereses"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def concepto_a_tipo_linea(concepto: str) -> str:
    norm = normalizar(concepto)
    for patron, tipo in TIPO_LINEA_MAP:
        if re.search(patron, norm):
            return tipo
    return "otro_ingreso"


def parse_valor(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[$,\s]", "", str(v).strip())
    if not s or s in ("-", "#N/A", "#n/a", "N/A", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def valor_celda(row, idx: int):
    c = row[idx] if idx < len(row) else None
    return c.value if c is not None else None


def hoja_a_periodo(hoja: str, anio: int = 2026) -> str:
    """'Enero' → '2026-01-01'"""
    tok = normalizar(hoja.split()[0])
    mes = MESES_MAP.get(tok)
    if not mes:
        raise ValueError(f"No se pudo derivar mes de hoja '{hoja}'. "
                         f"Disponibles: {list(MESES_MAP.keys())}")
    return f"{anio}-{mes}-01"


# ── Lectura del Excel ─────────────────────────────────────────────────────────
def leer_hoja(xlsx_path: str, hoja: str) -> list[dict]:
    """
    Lee filas donde Documento contable (col D) = 'Mandato'.
    Ignora filas con concepto 'Total' (filas de suma del Excel).
    """
    wb = load_workbook(xlsx_path, data_only=True)
    if hoja not in wb.sheetnames:
        raise ValueError(
            f"Hoja '{hoja}' no encontrada. Disponibles: {wb.sheetnames}"
        )
    sh = wb[hoja]
    filas = []
    for xl_row in sh.iter_rows(min_row=2, max_row=sh.max_row):
        proy = valor_celda(xl_row, 0)
        if not proy:
            continue
        doc = normalizar(str(valor_celda(xl_row, 3) or ""))
        if doc != "mandato":
            continue
        concepto = str(valor_celda(xl_row, 5) or "").strip()
        # Omitir filas de suma internas del Excel
        if normalizar(concepto) == "total":
            continue
        filas.append({
            "proyecto":    str(proy).strip(),
            "concepto":    concepto,
            "total":       parse_valor(valor_celda(xl_row, 6)),
            "nro_factura": str(valor_celda(xl_row, 7) or "").strip(),
            "codigo":      str(valor_celda(xl_row, 9) or "").strip()
                           if len(xl_row) > 9 else "",
        })
    wb.close()
    return filas


# ── API client ────────────────────────────────────────────────────────────────
class API:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def login(self, usuario: str, password: str):
        r = requests.post(
            f"{self.base}/api/v1/auth/token",
            data={"username": usuario, "password": password},
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        r = requests.get(f"{self.base}{path}", headers=self._h(), **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path, body, tolerante: bool = False):
        r = requests.post(f"{self.base}{path}", json=body, headers=self._h())
        if tolerante and r.status_code in (500, 502, 503):
            print(f"    ⚠  POST {path} → HTTP {r.status_code} (tolerado, Railway)")
            return None
        r.raise_for_status()
        return r.json()

    def patch(self, path, body):
        r = requests.patch(f"{self.base}{path}", json=body, headers=self._h())
        r.raise_for_status()
        return r.json()

    def delete(self, path):
        r = requests.delete(f"{self.base}{path}", headers=self._h())
        r.raise_for_status()


# ── Override manual para nombres ambiguos ─────────────────────────────────────
# Clave: nombre normalizado del Excel → nombre_comercial exacto en DB
NOMBRE_OVERRIDES: dict[str, str] = {
    normalizar("Sociedad Medica Rionegro S.A. Somer S.A."): "Somer Torre 1",
}


# ── Match de proyecto ─────────────────────────────────────────────────────────
def match_proyecto(proyectos_db: list, nombre: str) -> dict | None:
    norm = normalizar(nombre)

    # 0. Override manual (para colisiones conocidas)
    if norm in NOMBRE_OVERRIDES:
        target = normalizar(NOMBRE_OVERRIDES[norm])
        for p in proyectos_db:
            if normalizar(p["nombre_comercial"]) == target:
                return p

    # 1. Exact
    for p in proyectos_db:
        if normalizar(p["nombre_comercial"]) == norm:
            return p

    # 2. Substring
    for p in proyectos_db:
        n = normalizar(p["nombre_comercial"])
        if n in norm or norm in n:
            return p

    # 3. Token — primero tokens que matchean UN SOLO proyecto (más específicos)
    tokens = sorted([t for t in norm.split() if len(t) >= 4], key=len, reverse=True)
    for parte in tokens:
        matches = [p for p in proyectos_db
                   if parte in normalizar(p["nombre_comercial"])]
        if len(matches) == 1:
            return matches[0]

    # 4. Fallback: primer match de cualquier token
    for parte in tokens:
        for p in proyectos_db:
            if parte in normalizar(p["nombre_comercial"]):
                return p

    return None


# ── Limpiar liquidación ───────────────────────────────────────────────────────
def limpiar_liquidacion(api: API, liq_id: int):
    try:
        api.delete(f"/api/v1/liquidaciones/{liq_id}/limpiar")
        print(f"  ~ Liquidación {liq_id} limpiada (mandatos/costos/facturas borrados)")
    except Exception as exc:
        print(f"  ✗ Error limpiando liquidación {liq_id}: {exc}")
        raise


# ── Carga de una hoja ─────────────────────────────────────────────────────────
def cargar_hoja(
    api: API,
    filas: list[dict],
    periodo_date: str,
    proyectos_db: list,
    usuario_id: int,
    dry_run: bool,
    limpiar: bool,
    stats: dict,
):
    # Agrupar filas por proyecto
    grupos: dict[str, list] = {}
    for f in filas:
        grupos.setdefault(f["proyecto"], []).append(f)

    for nombre_proy, filas_proy in grupos.items():

        # ── Filtro: omitir si Ingreso Bruto es 0, None o #N/A ──────────────
        ingreso_bruto = None
        for f in filas_proy:
            if re.search(r"ingreso bruto|^ingreso$", normalizar(f["concepto"])):
                ingreso_bruto = f["total"]
                break
        if ingreso_bruto is None or ingreso_bruto == 0:
            print(f"  ⏭  Omitido (ingreso bruto cero/null/#N/A): '{nombre_proy}'")
            stats["omitidos"].append(nombre_proy)
            continue

        # ── Match con DB ────────────────────────────────────────────────────
        proy_db = match_proyecto(proyectos_db, nombre_proy)
        if not proy_db:
            stats["sin_match"].append(nombre_proy)
            print(f"  ⚠  Sin match en DB: '{nombre_proy}'")
            continue

        pid = proy_db["id"]
        print(f"\n  -> {nombre_proy}  (DB: '{proy_db['nombre_comercial']}' id={pid})")

        if dry_run:
            stats["ok"] += 1
            continue

        # ── Crear o recuperar liquidación ───────────────────────────────────
        liq_id = None
        try:
            liq_resp = api.post("/api/v1/liquidaciones", {
                "proyecto_id":     pid,
                "periodo":         periodo_date,
                "tipo_venta":      "autoconsumo",
                "generado_por_id": usuario_id,
            })
            liq_id = liq_resp["id"]
            print(f"     ✓ Liquidación creada id={liq_id}")
            stats["liq"] += 1
        except requests.HTTPError as e:
            if e.response.status_code in (409, 422, 500):
                resp = api.get("/api/v1/liquidaciones",
                               params={"proyecto_id": pid, "size": 50})
                y, m = periodo_date[:7].split("-")
                liq_id = next(
                    (l["id"] for l in resp["items"]
                     if l["periodo"].startswith(f"{y}-{m.zfill(2)}")),
                    None,
                )
                if not liq_id:
                    print(f"     ✗ No se pudo crear ni encontrar liquidación "
                          f"(status={e.response.status_code})")
                    continue
                print(f"     ~ Liquidación existente id={liq_id}")
            else:
                raise

        # ── Limpiar si se pidió ─────────────────────────────────────────────
        if limpiar:
            limpiar_liquidacion(api, liq_id)

        # ── Crear mandato de ingresos (nivel Total, sin inversionista) ──────
        m_resp = api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos", {
            "tipo":               "ingresos",
            "inversionista_id":   None,
            "beneficiario_nombre": None,
            "consecutivo":        None,
            "pa_aplica":          False,
        })
        if m_resp is None:
            print(f"     ✗ No se pudo crear mandato (error tolerado)")
            continue
        mid = m_resp["id"]
        stats["mandatos"] += 1
        print(f"     ✓ Mandato id={mid}")

        # ── Cargar líneas ───────────────────────────────────────────────────
        neto_pagar = None
        orden = 0
        for f in filas_proy:
            if not f["concepto"] or f["total"] is None:
                continue

            norm_c = normalizar(f["concepto"])

            # "Valor a Pagar" → valor_neto_cop del mandato, no es línea
            if re.search(r"valor.*pagar|valor.*ganancia", norm_c):
                neto_pagar = f["total"]
                continue

            tipo_l = concepto_a_tipo_linea(f["concepto"])
            result = api.post(
                f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}/lineas",
                {
                    "tipo_linea":         tipo_l,
                    "concepto":           f["concepto"],
                    "valor_cop":          f["total"],
                    "referencia_factura": f["nro_factura"] or None,
                    "orden":              orden,
                },
                tolerante=True,   # tolerante a 500 de Railway post-commit
            )
            if result is not None:
                stats["lineas"] += 1
            orden += 1

        # ── Parchear valor_neto_cop ─────────────────────────────────────────
        if neto_pagar is not None:
            api.patch(
                f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}",
                {"valor_neto_cop": neto_pagar},
            )
            print(f"     ✓ valor_neto_cop = $ {neto_pagar:,.0f}")

        stats["ok"] += 1


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Carga autoconsumo 2026 desde Excel al sistema de liquidaciones"
    )
    parser.add_argument("--xlsx",     required=True,  help="Ruta al Excel")
    parser.add_argument("--hojas",    nargs="+",       default=["Enero"],
                        help="Hojas a procesar (ej: Enero Febrero Marzo Abril)")
    parser.add_argument("--anio",     type=int,        default=2026)
    parser.add_argument("--api-url",  default="https://backend-production-63d8.up.railway.app")
    parser.add_argument("--usuario",  required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dry-run",  action="store_true",
                        help="Imprime qué haría sin escribir nada")
    parser.add_argument("--limpiar",  action="store_true",
                        help="Borra mandatos/costos/facturas antes de reimportar")
    args = parser.parse_args()

    # Autenticación
    print(f"Autenticando en {args.api_url} ...")
    api = API(args.api_url)
    api.login(args.usuario, args.password)
    print("Autenticado ✓\n")

    # Cargar proyectos de DB una sola vez
    proyectos_db = api.get("/api/v1/proyectos", params={"size": 500})["items"]
    print(f"{len(proyectos_db)} proyectos en DB")

    usuario_id = api.get("/api/v1/auth/me")["id"]

    stats = {
        "ok": 0, "liq": 0, "mandatos": 0, "lineas": 0,
        "sin_match": [], "omitidos": [],
    }

    for hoja in args.hojas:
        periodo_date = hoja_a_periodo(hoja, args.anio)
        sep = "=" * 55
        print(f"\n{sep}")
        print(f"Hoja: {hoja}  →  período {periodo_date}")
        print(sep)

        filas = leer_hoja(args.xlsx, hoja)
        print(f"  {len(filas)} filas Mandato leídas")

        if args.dry_run:
            print("  [DRY RUN — no se escribirá nada en la API]")

        cargar_hoja(
            api, filas, periodo_date, proyectos_db,
            usuario_id, args.dry_run, args.limpiar, stats,
        )

    # ── Resumen final ─────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("RESUMEN FINAL")
    print("=" * 55)
    print(f"  Proyectos cargados:     {stats['ok']}")
    print(f"  Liquidaciones creadas:  {stats['liq']}")
    print(f"  Mandatos creados:       {stats['mandatos']}")
    print(f"  Líneas creadas:         {stats['lineas']}")
    print(f"  Omitidos (ing=0/#N/A):  {len(stats['omitidos'])}")
    if stats["omitidos"]:
        for n in stats["omitidos"]:
            print(f"    - {n}")
    if stats["sin_match"]:
        print(f"\n  ⚠  Sin match en DB ({len(stats['sin_match'])}):")
        for n in stats["sin_match"]:
            print(f"    - {n}")
    else:
        print("\n  ✓ Todos los proyectos activos encontrados en DB.")


if __name__ == "__main__":
    main()
