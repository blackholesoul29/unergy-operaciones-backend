#!/usr/bin/env python3
"""
Carga un panel de seguimiento contable (XLSX) al sistema de liquidaciones.
Lee hipervínculos directamente desde el archivo Excel para obtener los
links a Drive de cada soporte.

Uso:
  python scripts/cargar_liquidaciones_csv.py \
      --xlsx "ruta/al/2026_Panel de seguimiento contable.xlsx" \
      --hoja Enero \
      --periodo 2026-01 \
      --api-url https://backend-production-63d8.up.railway.app \
      --usuario admin@unergy.co \
      --password TU_PASSWORD

Hojas disponibles: Enero, Febrero, Marzo, Abril prueba costos, etc.
"""
import argparse, re, sys
from openpyxl import load_workbook
import requests


# ── Mapping concepto → tipo_linea ─────────────────────────────────────────────
TIPO_LINEA_MAP = [
    (r"ingreso bruto",                         "ingreso_bruto"),
    (r"^ingreso$",                             "ingreso_bruto"),
    (r"despacho",                              "despacho"),
    (r"ventas en bolsa",                       "ventas_en_bolsa"),
    (r"compras en bolsa|compras a ",           "compras_en_bolsa"),
    (r"redistribuci",                          "redistribucion_ingresos"),
    (r"comercializaci",                        "ajuste_comercializacion"),
    (r"ajuste.*xm|xm.*ajuste",                "ajuste_xm"),
    (r"ajuste.*unergy",                        "ajuste_unergy"),
    (r"ajuste.*administr",                     "otro_costo"),
    (r"arriendo",                              "arriendo"),
    (r"mantenimiento",                         "mantenimiento"),
    (r"iva.*internet|internet.*iva",           "iva_internet"),  # Bug 2: before generic internet rule
    (r"internet",                              "servicio_internet"),
    (r"poliza.*cumplimiento|p.liza.*cumpl",    "poliza_cumplimiento"),
    (r"poliza|incendio|lucro cesante",         "seguro"),
    (r"servicios p.blicos|consumo de energ",   "servicios_publicos_consumo"),
    (r"cambio.*equipo|equipo.*medida",         "cambio_equipos_medida"),
    (r"representaci",                          "representacion"),
    (r"^cgm",                                  "cgm"),
    (r"administraci|valor final",              "administracion"),
    (r"reteica",                               "reteica"),
    (r"ica opex",                              "ica_opex"),
    (r"iva|i\.v\.a",                           "iva"),
    (r"retenci",                               "retencion_fuente"),
    (r"porcentaje.*participaci",               "porcentaje_participacion"),
    (r"valor.*pagar|valor.*ganancia|utilidad", "valor_a_pagar"),
    (r"intereses",                             "intereses"),
]

# Bug 4: doc types válidos y mapa de normalización a title-case
_DOC_CONTABLE_MAP = {
    "informacion": "Información",
    "mandato":     "Mandato",
    "costos":      "Costos",
    "factura":     "Factura",
    "buenaventura": "Buenaventura",
}
TIPOS_VALIDOS_DOC = set(_DOC_CONTABLE_MAP.keys())


def normalizar_doc_contable(s: str) -> str:
    """Normaliza el valor de Documento contable: trim + title-case canónico."""
    return _DOC_CONTABLE_MAP.get(normalizar(s), s.strip())


def normalizar(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or "").lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def concepto_a_tipo_linea(concepto: str) -> str:
    norm = normalizar(concepto)
    for patron, tipo in TIPO_LINEA_MAP:
        if re.search(patron, norm):
            return tipo
    return "otro_ingreso"


def concepto_a_tipo_costo(concepto: str) -> str:
    norm = normalizar(concepto)
    if "arriendo" in norm:                          return "arriendo"
    if "mantenimiento" in norm:                     return "mantenimiento"
    if "internet" in norm:                          return "internet"
    if "poliza" in norm or "p.liza" in norm:        return "polizas"
    if "servicios p" in norm:                       return "servicios_publicos"
    if "cambio" in norm and "equipo" in norm:       return "cambio_equipos_medida"
    if "comercializaci" in norm:                    return "comercializacion_xm"
    return "otro"


def concepto_a_tipo_factura(concepto: str) -> str:
    norm = normalizar(concepto)
    if "representaci" in norm:  return "representacion"
    if "cgm" in norm:           return "cgm"
    return "administracion_operacion"


def parse_valor(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[$,\s]", "", str(v).strip())
    if not s or s in ("-", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def celda(row, idx: int):
    """Valor de celda o None si fuera de rango."""
    return row[idx] if idx < len(row) else None


def link(row, idx: int) -> str | None:
    """Hipervínculo de la celda o None."""
    cell = row[idx] if idx < len(row) else None
    if cell and hasattr(cell, "hyperlink") and cell.hyperlink:
        return cell.hyperlink.target
    return None


def valor(row, idx: int):
    c = celda(row, idx)
    return c.value if c is not None else None


# ── Leer hoja XLSX preservando hipervínculos ──────────────────────────────────
def leer_hoja(xlsx_path: str, hoja: str) -> tuple[list[dict], dict[str, str]]:
    """
    Devuelve (filas, er_map) donde:
    - filas: lista de dicts con datos de la tabla principal (cols A-K)
    - er_map: dict {nombre_proyecto_normalizado: er_url} leído de la tabla
              lateral derecha (col N = proyecto, col O = ER URL)

    Índices 0-based:
      0=Proyecto  1=Inversionista  2=DocContable  5=Concepto  6=Total
      7=RefFactura  8=ConsIng(soporte_url)  9=ConsCostos  10=Comprobante
      13=ProyectoER  14=EstadoResultados(URL)  15=CarpetaProyecto
    """
    wb = load_workbook(xlsx_path, data_only=True)
    if hoja not in wb.sheetnames:
        raise ValueError(f"Hoja '{hoja}' no encontrada. Disponibles: {wb.sheetnames}")
    sh = wb[hoja]

    rows = []
    er_map: dict[str, str] = {}

    for xl_row in sh.iter_rows(min_row=2, max_row=sh.max_row):
        # ── Tabla lateral: col N → proyecto, col O → ER URL ──
        if len(xl_row) > 14:
            n_val = valor(xl_row, 13)
            o_cell = xl_row[14]
            if n_val:
                er_url = (o_cell.hyperlink.target if o_cell.hyperlink else None) \
                         or str(o_cell.value or "").strip()
                if er_url and er_url.startswith("http"):
                    er_map[normalizar(str(n_val).strip())] = er_url

        # ── Tabla principal: col A debe tener proyecto ──
        proy = valor(xl_row, 0)
        if not proy:
            continue
        rows.append({
            "proyecto":        str(proy).strip(),
            "inversionista":   str(valor(xl_row, 1) or "").strip(),
            "doc_contable":    normalizar_doc_contable(str(valor(xl_row, 2) or "")),
            "concepto":        str(valor(xl_row, 5) or "").strip(),
            "total":           parse_valor(valor(xl_row, 6)),
            "ref_factura":     str(valor(xl_row, 7) or "").strip(),
            "ref_factura_url": link(xl_row, 7),
            "cons_ing_txt":    str(valor(xl_row, 8) or "").strip(),
            "cons_ing_url":    link(xl_row, 8),    # ← link directo al PDF en Drive
            "cons_cos_txt":    str(valor(xl_row, 9) or "").strip() if len(xl_row) > 9 else "",
            "comprobante":     str(valor(xl_row, 10) or "").strip() if len(xl_row) > 10 else "",
            "carpeta_url":     link(xl_row, 15),
        })
    wb.close()
    return rows, er_map


# ── API client ────────────────────────────────────────────────────────────────
class API:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def login(self, usuario: str, password: str):
        r = requests.post(f"{self.base}/api/v1/auth/token",
                          data={"username": usuario, "password": password})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        r = requests.get(f"{self.base}{path}", headers=self._h(), **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = requests.post(f"{self.base}{path}", json=body, headers=self._h())
        r.raise_for_status()
        return r.json()

    def patch(self, path, body):
        r = requests.patch(f"{self.base}{path}", json=body, headers=self._h())
        r.raise_for_status()
        return r.json()


# ── Match helpers ─────────────────────────────────────────────────────────────
def match_proyecto(proyectos_db: list, nombre: str) -> dict | None:
    norm = normalizar(nombre)
    for p in proyectos_db:
        if normalizar(p["nombre_comercial"]) == norm:
            return p
    for p in proyectos_db:
        n = normalizar(p["nombre_comercial"])
        if n in norm or norm in n:
            return p
    partes = norm.split()
    for parte in reversed(partes):
        if len(parte) < 4:
            continue
        for p in proyectos_db:
            if parte in normalizar(p["nombre_comercial"]):
                return p
    return None


def match_inversionista(inversionistas_db: list, nombre: str) -> dict | None:
    if not nombre or nombre.upper() == "TOTAL":
        return None
    norm = normalizar(nombre)
    for inv in inversionistas_db:
        cn = normalizar(inv.get("cliente_nombre") or "")
        if cn and (cn in norm or norm in cn):
            return inv
        palabras = [w for w in norm.split() if len(w) > 4]
        if palabras and cn and all(w in cn for w in palabras[:2]):
            return inv
    return None


# ── Carga principal ───────────────────────────────────────────────────────────
def cargar(api: API, filas: list[dict], er_map: dict[str, str], periodo_date: str, dry_run: bool):
    # Bug 4: validar tipos de Documento contable desconocidos
    tipos_desconocidos: dict[str, list[int]] = {}
    for i, f in enumerate(filas, start=2):
        nd = normalizar(f["doc_contable"])
        if nd and nd not in TIPOS_VALIDOS_DOC:
            tipos_desconocidos.setdefault(f["doc_contable"], []).append(i)
    if tipos_desconocidos:
        print("\n⚠  TIPOS NO RECONOCIDOS en 'Documento contable':")
        for tipo, filas_idx in tipos_desconocidos.items():
            print(f"   '{tipo}' → filas: {filas_idx[:10]}{'…' if len(filas_idx) > 10 else ''}")
        print("   Estas filas serán ignoradas. Revisar el archivo o agregar al mapa.\n")

    me = api.get("/api/v1/auth/me")
    usuario_id = me["id"]

    proyectos_db = api.get("/api/v1/proyectos", params={"size": 500})["items"]
    print(f"  {len(proyectos_db)} proyectos en DB")

    # Agrupar filas: proyecto → inversionista → lista de filas
    grupos: dict[str, dict[str, list]] = {}

    for f in filas:
        grupos.setdefault(f["proyecto"], {}).setdefault(f["inversionista"], []).append(f)

    stats = {"ok": 0, "sin_match": [], "liq": 0,
             "mandatos": 0, "lineas": 0, "costos": 0, "facturas": 0}

    for nombre_proy, inv_grupos in grupos.items():
        proy_db = match_proyecto(proyectos_db, nombre_proy)
        if not proy_db:
            stats["sin_match"].append(nombre_proy)
            print(f"  ⚠  Sin match: '{nombre_proy}'")
            continue

        pid = proy_db["id"]
        er_url = er_map.get(normalizar(nombre_proy))
        print(f"\n-> {nombre_proy} (id={pid})")

        if dry_run:
            invs = list(inv_grupos.keys())
            print(f"   Inversionistas: {invs}")
            stats["ok"] += 1
            continue

        proy_detail = api.get(f"/api/v1/proyectos/{pid}")
        inversionistas_db = proy_detail.get("inversionistas", [])

        # Crear / recuperar liquidación
        try:
            liq_resp = api.post("/api/v1/liquidaciones", {
                "proyecto_id": pid,
                "periodo": periodo_date,
                "tipo_venta": "ppa",
                "generado_por_id": usuario_id,
            })
            liq_id = liq_resp["id"]
            print(f"  ✓ Liquidación creada id={liq_id}")
            stats["liq"] += 1
        except requests.HTTPError as e:
            if e.response.status_code in (409, 422, 500):
                # 409 = duplicate; 500 might also be a duplicate before migration fix
                resp = api.get("/api/v1/liquidaciones",
                               params={"proyecto_id": pid, "size": 50})
                y, m = periodo_date[:7].split("-")
                liq_id = next(
                    (l["id"] for l in resp["items"]
                     if l["periodo"].startswith(f"{y}-{m.zfill(2)}")), None)
                if not liq_id:
                    print(f"  ✗ No se pudo crear ni encontrar liquidación (status={e.response.status_code})")
                    continue
                print(f"  ~ Liquidación existente id={liq_id}")
            else:
                raise

        # Actualizar metadatos de la liquidación
        patch_body: dict = {}
        if er_url:
            patch_body["estado_resultados_url"] = er_url
        total_rows = inv_grupos.get("Total", [])
        for f in total_rows:
            if f["doc_contable"].lower() == "información":
                if f["comprobante"]:
                    patch_body["comprobante_contable_ref"] = f["comprobante"]
                if f["cons_ing_txt"].isdigit():
                    patch_body["consecutivo_inicial_ingresos"] = int(f["cons_ing_txt"])
                if f["cons_cos_txt"].isdigit():
                    patch_body["consecutivo_inicial_costos"] = int(f["cons_cos_txt"])
        if patch_body:
            api.patch(f"/api/v1/liquidaciones/{liq_id}", patch_body)

        # Procesar cada grupo de inversionista
        for inv_nombre, filas_inv in inv_grupos.items():
            es_total = inv_nombre.upper() == "TOTAL"
            inv_db = None if es_total else match_inversionista(inversionistas_db, inv_nombre)
            inv_id = inv_db["id"] if inv_db else None

            # Consecutivos del row Información de este inversionista
            cons_ing = cons_cos = None
            for f in filas_inv:
                if f["doc_contable"].lower() == "información":
                    if f["cons_ing_txt"].isdigit():
                        cons_ing = int(f["cons_ing_txt"])
                    if f["cons_cos_txt"].isdigit():
                        cons_cos = int(f["cons_cos_txt"])

            # Bug 1/3: "Buenaventura" contiene Representación/CGM → es Factura, no Mandato
            filas_ing = [f for f in filas_inv
                         if f["doc_contable"].lower() == "mandato"]
            filas_cos = [f for f in filas_inv
                         if f["doc_contable"].lower() == "costos"]
            filas_fac = [f for f in filas_inv
                         if f["doc_contable"].lower() in ("factura", "buenaventura")]

            # ── Mandato de ingresos ──
            lineas_ing = [f for f in filas_ing
                          if f["concepto"] and
                          normalizar(f["concepto"]) not in ("porcentaje de participacion", "valor a pagar")
                          and f["total"] is not None]
            if lineas_ing:
                m_resp = api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos", {
                    "tipo": "ingresos",
                    "inversionista_id": inv_id,
                    "beneficiario_nombre": inv_nombre if not es_total else None,
                    "consecutivo": cons_ing,
                    "pa_aplica": inv_db.get("es_patrimonio_autonomo", False) if inv_db else False,
                })
                mid = m_resp["id"]
                stats["mandatos"] += 1

                neto_pagar = None
                for orden, f in enumerate(filas_ing):
                    if not f["concepto"] or f["total"] is None:
                        continue
                    if normalizar(f["concepto"]) == "valor a pagar":
                        neto_pagar = f["total"]
                        continue
                    tipo_l = concepto_a_tipo_linea(f["concepto"])
                    # referencia: combina ref_factura + nombre soporte si son distintos
                    ref_parts = [f["ref_factura"]]
                    if f["cons_ing_txt"] and not f["cons_ing_txt"].isdigit() and f["cons_ing_txt"] != f["ref_factura"]:
                        ref_parts.append(f["cons_ing_txt"])
                    ref = " | ".join(p for p in ref_parts if p) or None
                    api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}/lineas", {
                        "tipo_linea": tipo_l,
                        "concepto": f["concepto"],
                        "valor_cop": f["total"],
                        "referencia_factura": ref,
                        "orden": orden,
                    })
                    stats["lineas"] += 1

                if neto_pagar is not None:
                    api.patch(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}",
                              {"valor_neto_cop": neto_pagar})

            # ── Mandato de costos ──
            lineas_cos = [f for f in filas_cos
                          if f["concepto"] and f["total"] is not None
                          and normalizar(f["concepto"]) not in ("porcentaje de participacion", "valor a pagar")]
            if lineas_cos:
                mc_resp = api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos", {
                    "tipo": "costos",
                    "inversionista_id": inv_id,
                    "beneficiario_nombre": inv_nombre if not es_total else None,
                    "consecutivo": cons_cos,
                    "pa_aplica": inv_db.get("es_patrimonio_autonomo", False) if inv_db else False,
                })
                mcid = mc_resp["id"]
                stats["mandatos"] += 1

                neto_cos = None
                for orden, f in enumerate(filas_cos):
                    if not f["concepto"] or f["total"] is None:
                        continue
                    if normalizar(f["concepto"]) == "valor a pagar":
                        neto_cos = f["total"]
                        continue
                    tipo_l = concepto_a_tipo_linea(f["concepto"])
                    ref_parts = [f["ref_factura"]]
                    if f["cons_ing_txt"] and not f["cons_ing_txt"].isdigit() and f["cons_ing_txt"] != f["ref_factura"]:
                        ref_parts.append(f["cons_ing_txt"])
                    ref = " | ".join(p for p in ref_parts if p) or None
                    api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mcid}/lineas", {
                        "tipo_linea": tipo_l,
                        "concepto": f["concepto"],
                        "valor_cop": f["total"],
                        "referencia_factura": ref,
                        "orden": orden,
                    })
                    stats["lineas"] += 1

                    # LiquidacionCosto solo para el Total (nivel proyecto)
                    if es_total and f["total"] != 0:
                        api.post(f"/api/v1/liquidaciones/{liq_id}/costos", {
                            "tipo_costo": concepto_a_tipo_costo(f["concepto"]),
                            "descripcion": f["concepto"],
                            "nro_soporte": (f["ref_factura"] or f["comprobante"]) or None,
                            "soporte_url": f["cons_ing_url"],  # ← link al PDF en Drive
                            "valor_cop": f["total"],
                        })
                        stats["costos"] += 1

                if neto_cos is not None:
                    api.patch(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mcid}",
                              {"valor_neto_cop": neto_cos})

            # ── Facturas de servicio (solo Total = nivel proyecto) ──
            if es_total:
                for f in filas_fac:
                    if not f["concepto"] or f["total"] is None:
                        continue
                    api.post(f"/api/v1/liquidaciones/{liq_id}/facturas", {
                        "tipo_servicio": concepto_a_tipo_factura(f["concepto"]),
                        "numero_factura": f["ref_factura"] or None,
                        "nro_soporte": f["cons_ing_txt"] or None,
                        "soporte_url": f["cons_ing_url"],   # ← link al PDF en Drive
                        "valor_cop": f["total"],
                    })
                    stats["facturas"] += 1

        stats["ok"] += 1

    print("\n" + "=" * 50)
    print(f"Proyectos cargados:     {stats['ok']}")
    print(f"Liquidaciones creadas:  {stats['liq']}")
    print(f"Mandatos creados:       {stats['mandatos']}")
    print(f"Líneas creadas:         {stats['lineas']}")
    print(f"Costos (nivel proy):    {stats['costos']}")
    print(f"Facturas creadas:       {stats['facturas']}")
    if stats["sin_match"]:
        print(f"\nSin match en DB ({len(stats['sin_match'])}):")
        for n in stats["sin_match"]:
            print(f"  - {n}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx",     required=True)
    p.add_argument("--hoja",     default="Enero")
    p.add_argument("--periodo",  required=True, help="YYYY-MM  ej: 2026-01")
    p.add_argument("--api-url",  default="https://backend-production-63d8.up.railway.app")
    p.add_argument("--usuario",  required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--dry-run",  action="store_true")
    args = p.parse_args()

    y, m = args.periodo.split("-")
    periodo_date = f"{y}-{m.zfill(2)}-01"

    print(f"Leyendo hoja '{args.hoja}' de {args.xlsx} ...")
    filas, er_map = leer_hoja(args.xlsx, args.hoja)
    print(f"  {len(filas)} filas leídas, {len(er_map)} proyectos con ER URL")

    if args.dry_run:
        print("\n[DRY RUN — no se escribira nada en la API]\n")

    print(f"Autenticando en {args.api_url}...")
    api = API(args.api_url)
    api.login(args.usuario, args.password)
    print("Autenticado\n")

    cargar(api, filas, er_map, periodo_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
