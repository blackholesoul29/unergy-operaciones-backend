#!/usr/bin/env python3
"""
Carga un panel de seguimiento contable (CSV) al sistema de liquidaciones.

Uso:
  python scripts/cargar_liquidaciones_csv.py \
      --csv "ruta/al/archivo.csv" \
      --periodo 2026-01 \
      --api-url https://backend-production-63d8.up.railway.app \
      --usuario admin@unergy.co \
      --password TU_PASSWORD

El periodo se escribe como YYYY-MM (se guarda como primer día del mes).
"""
import argparse, csv, re, sys, json
from datetime import date

import requests

# ── Carpetas madre Drive por proyecto (hoja autoconsumo) ──────────────────────
DRIVE_CARPETA_MADRE = {
    "uruaco":        "1Fc67fN-DyWq_0ERoBCRcnogqX4kO1grg",
    "cañahuate":     "1E5xNqAw6B7RmFiF7mia6KIar4BAoxiVY",
    "gandalf":       "1fFRsyKxJZOm2A2hDeVwm4h1NigCYzaRM",
    "vallenata":     "1fFuTXbIrBX-OqHjkwkA5mvgnK9gUBNLT",
    "el molino":     "19QGZabUJz6OfyC9_B0xWftxf6vVGEKLb",
    "verso":         "152ZPMAKE5C3vP-o17fS-trOBWkZXI07J",
    "esmeralda":     "1l_HQqN-MBMf5MLhQsRnQHRHsD7OMzvBC",
    "villanueva":    "1jX5-koxaVQvoq9YYucpvoIxyTbX3s3PN",
    "la puya":       "1DDF3tcP2eax1imyfnxWYX3LZ3f6koNET",
    "perijá":        "1vI60Sawfzld4AgfvNa6pHZ9xtt17IKpY",
    "perija":        "1vI60Sawfzld4AgfvNa6pHZ9xtt17IKpY",
    "el olimpo":     "1a6gW65P09DZnDuxvL3vDKJI4nBpuNE4m",
    "la mesa":       "11V9KD2yaE2DQSZ53wWNKJ7jX-sdEBgUH",
    "leyenda":       "1EIZT8U8u5XPsHgKYuWRxj9Hv0epBNd0E",
    "baraya":        "1Srq-198jnGeObT22ZqVbaSCvKjiaAxqv",
    "merengue":      "1L8v8ltJP8VOkUO8Ur-v3a0pg6A-k0Fpk",
    "cope":          "1v1Hr-nrLwrvoAu5htxN-d8cRJNUtYxie",
    "joropo":        "1fC663EQ6kQxZDuVzTv58jSvrz5jmHLgC",
    "mapalé":        "1E6WUIlhpZXNHVB_frzS_Lza-hWGY9DBS",
    "mapale":        "1E6WUIlhpZXNHVB_frzS_Lza-hWGY9DBS",
    "chima":         "1u8baLyPE37dDOwHGLEvdh0tBW7Axae3T",
    "ibirico":       "1sywaNq1C_JOwr7SFK-ePQL6e1vryNMLY",
    "el son":        "1h6P5o2X3rwwAOs4I330xuJ-woSkmehlR",
    "la reserva":    "1Up-x2T5rWuUdAmHZpHygTtRCxvlv6db2",
    "naos 1":        "128aFOFlv0IVtsqZZciYicMQJvt7IY0j1",
    "naos 2":        "16Itu_9TdADSn_-Q-yZKAZqBLvIzuDD0a",
    "naos 3":        "1mwtW03hvkO-28ak2wear27K7t7bhflqL",
    "polaris 1":     "1P-1_iFF3RwRYyIY4mzrtw3oFAkJ5pxvT",
    "san onofre":    "1ilESL-tgTH7YPIoxZ5G4rWXCIsLQY6Dy",
    "delta 1":       "1F3xq78p0aNULBNzrP05Kk8Nyvi57VsuQ",
    "bayunca":       "1mBy8pkw8Jqp_qAmLlMbxEFtDSaE5eKkC",
    "delta 2":       "1Kir1rYnzi2z_cP_Lcrcgp061mc3mxOIw",
    "polaris 2":     "1OPC7N-wRjZ-toFtJV01iYgIYJoa6eYt3",
    "marimonda":     "18Sz0mB0eFo5XmeTUBpilcTjtAXegihlj",
    "agustin 1":     "1NbYmkCeP_LZ3D2dI6l6Z1lU6gCbIPCMW",
    "san diego":     "1pKtL21qpWJS8dDHL9ZwMHHhhQLdABD5t",
    "yuan solar":    "1zfDkcw-MioonZGKAiDhlvX8tRkeFvQtU",
    "yurbaqua":      "1A7_PX7uhsF6tgnJcKArTO6T8Q9KUuT3a",
    "catedral":      "1RZ-oCRsbz_8AIQ4Rc32a_k7lKtx5CQ7R",
    "sirius":        "1QUpNQV1X35QYoboOUfuBSRdONqCUi0Xs",
    "bongos":        "1Ow4sl2oQrGBM0TnOIp6eTb_NSV6mEZC2",
    "valencia 1":    "19EXomn_Q4aD9vFoimEB4cHzwhRuuy83H",
    "valencia 2":    "16wmsrFpMHon_9o-QMShWOaM4G7ScS_I4",
    "cacica":        "1zP-GGcnvTAl0WYafRSlSW4grhSv6FmqA",
    "piloneras":     "1ZcKynDlfJ6s5u3LsvrjTTb5Qo5LrmJWm",
    "astrolumen":    "14q79BduN41-KDEkVw7Y3BEy9dVt5JgMc",
    "biosolar":      "1_gv_eG4NLzWkvBAOcYSJYYUGEPIA_2Mw",
    "cienaga":       "1Cqlg28ZEg4sfHqCP5_MiZ59GU69SMJV0",
    "ciénaga":       "1Cqlg28ZEg4sfHqCP5_MiZ59GU69SMJV0",
    "cumbia":        "1OuLuBwsRDQrefIpYOaPNfpzmnFtRGOQJ",
    "san pelayo":    "1rAmM0GqKPYK0EufSvdQD88K2keya2p6K",
    "chiriguana 2":  "1YypivxQI4En5hFMJLpTk50Bc_DFXbcjH",
    "chiriguana 4":  "1pBjqM0KMF1pBG5bVr-eSZFDo8Gih6fFZ",
}

# Mapping concepto CSV (lowercase, sin acentos) → tipo_linea enum
TIPO_LINEA_MAP = [
    (r"ingreso bruto",                    "ingreso_bruto"),
    (r"^ingreso$",                        "ingreso_bruto"),
    (r"ingreso bruto biac",               "ingreso_bruto"),
    (r"ingreso bruto bolsa",              "ingreso_bruto"),
    (r"ingreso bruto comprensaci",        "ingreso_bruto"),
    (r"ingreso bruto cox",                "ingreso_bruto"),
    (r"ingreso bruto ungc",               "ingreso_bruto"),
    (r"ingreso bruto ungg",               "ingreso_bruto"),
    (r"despacho",                         "despacho"),
    (r"ventas en bolsa",                  "ventas_en_bolsa"),
    (r"compras en bolsa",                 "compras_en_bolsa"),
    (r"compras a ",                       "compras_en_bolsa"),
    (r"redistribuci",                     "redistribucion_ingresos"),
    (r"comercializaci",                   "ajuste_comercializacion"),
    (r"ajuste.*xm|xm.*ajuste",           "ajuste_xm"),
    (r"ajuste.*unergy",                   "ajuste_unergy"),
    (r"ajuste.*administr",                "otro_costo"),
    (r"arriendo",                         "arriendo"),
    (r"mantenimiento",                    "mantenimiento"),
    (r"internet",                         "servicio_internet"),
    (r"poliza.*cumplimiento|p.liza.*cumpl","poliza_cumplimiento"),
    (r"poliza|incendio|lucro cesante|p.liza incen", "seguro"),
    (r"servicios p.blicos",               "servicios_publicos_consumo"),
    (r"cambio.*equipo|equipo.*medida",    "cambio_equipos_medida"),
    (r"representaci",                     "representacion"),
    (r"^cgm",                             "cgm"),
    (r"administraci|valor final",         "administracion"),
    (r"reteica",                          "reteica"),
    (r"ica opex",                         "ica_opex"),
    (r"iva|i\.v\.a",                      "iva"),
    (r"retenci",                          "retencion_fuente"),
    (r"porcentaje.*participaci",          "porcentaje_participacion"),
    (r"valor.*pagar|valor.*ganancia|utilidad", "valor_a_pagar"),
    (r"intereses",                        "intereses"),
]

TIPO_FACTURA_MAP = {
    "representaci": "representacion",
    "cgm":          "cgm",
    "administraci": "administracion_operacion",
}


def normalizar(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def concepto_a_tipo_linea(concepto: str) -> str:
    norm = normalizar(concepto)
    for patron, tipo in TIPO_LINEA_MAP:
        if re.search(patron, norm):
            return tipo
    return "otro_ingreso"


def parse_valor(s: str) -> float | None:
    if not s or s.strip() in ("", "-", "$-"):
        return None
    s = re.sub(r"[$,\s]", "", s.strip())
    try:
        return float(s)
    except ValueError:
        return None


def drive_folder_url(nombre_proyecto: str) -> str | None:
    norm = normalizar(nombre_proyecto)
    # Quitar prefijos comunes
    for prefijo in ("minigranja solar ", "gd ", "minigranja "):
        if norm.startswith(prefijo):
            norm = norm[len(prefijo):]
            break
    for key, fid in DRIVE_CARPETA_MADRE.items():
        if key in norm or norm in key:
            return f"https://drive.google.com/drive/folders/{fid}"
    return None


def extraer_er_urls(rows: list[list]) -> dict[str, str]:
    """Extrae mapa proyecto→URL de Estado de Resultados del CSV (col 13 y 14)."""
    er = {}
    for row in rows:
        if len(row) > 14 and row[14].strip().startswith("http"):
            nombre = row[13].strip()
            url = row[14].strip()
            if nombre:
                er[normalizar(nombre)] = url
    return er


class APIClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token = None

    def login(self, usuario: str, password: str):
        r = requests.post(f"{self.base}/api/v1/auth/login",
                          data={"username": usuario, "password": password})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **kw) -> dict:
        r = requests.get(f"{self.base}{path}", headers=self._h(), **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json_body: dict) -> dict:
        r = requests.post(f"{self.base}{path}", json=json_body, headers=self._h())
        r.raise_for_status()
        return r.json()

    def patch(self, path: str, json_body: dict) -> dict:
        r = requests.patch(f"{self.base}{path}", json=json_body, headers=self._h())
        r.raise_for_status()
        return r.json()


def buscar_proyecto(proyectos: list, nombre_csv: str) -> dict | None:
    norm_csv = normalizar(nombre_csv)
    # 1. Exacto
    for p in proyectos:
        if normalizar(p["nombre_comercial"]) == norm_csv:
            return p
    # 2. El nombre del CSV contiene el nombre del proyecto (o viceversa)
    for p in proyectos:
        norm_p = normalizar(p["nombre_comercial"])
        if norm_p in norm_csv or norm_csv in norm_p:
            return p
    # 3. Palabras clave (última palabra del nombre CSV)
    partes = norm_csv.split()
    for parte in reversed(partes):
        if len(parte) < 4:
            continue
        for p in proyectos:
            if parte in normalizar(p["nombre_comercial"]):
                return p
    return None


def buscar_inversionista(inversionistas: list, nombre_csv: str) -> dict | None:
    if not nombre_csv or nombre_csv.upper() == "TOTAL":
        return None
    norm = normalizar(nombre_csv)
    for inv in inversionistas:
        nombre_cliente = normalizar(inv.get("cliente_nombre") or "")
        if nombre_cliente and (nombre_cliente in norm or norm in nombre_cliente):
            return inv
        # Match por palabras
        palabras = [w for w in norm.split() if len(w) > 4]
        if palabras and all(w in nombre_cliente for w in palabras[:2]):
            return inv
    return None


def cargar_csv(api: APIClient, csv_path: str, periodo: str, dry_run: bool = False):
    # Parsear periodo
    y, m = periodo.split("-")
    periodo_date = f"{y}-{m.zfill(2)}-01"

    # Leer CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    data_rows = rows[1:]  # saltar header

    # Extraer mapa de Estado de Resultados
    er_urls = extraer_er_urls(data_rows)

    # Obtener proyectos de la API
    print("Obteniendo proyectos...")
    proyectos_resp = api.get("/api/v1/proyectos", params={"size": 500})
    proyectos_db = proyectos_resp["items"]
    print(f"  {len(proyectos_db)} proyectos en DB")

    # Obtener usuario actual para generado_por_id
    me = api.get("/api/v1/auth/me")
    usuario_id = me["id"]

    # Agrupar filas por proyecto → inversionista
    grupos: dict[str, dict[str, list]] = {}
    for row in data_rows:
        if len(row) < 7:
            continue
        proyecto = row[0].strip()
        inversionista = row[1].strip()
        if not proyecto:
            continue
        grupos.setdefault(proyecto, {}).setdefault(inversionista, []).append(row)

    stats = {"proyectos_ok": 0, "proyectos_no_match": [], "liq_creadas": 0,
             "mandatos": 0, "lineas": 0, "costos": 0, "facturas": 0}

    for nombre_proy, inv_grupos in grupos.items():
        proyecto_db = buscar_proyecto(proyectos_db, nombre_proy)
        if not proyecto_db:
            stats["proyectos_no_match"].append(nombre_proy)
            print(f"  ⚠ Sin match: '{nombre_proy}'")
            continue

        pid = proyecto_db["id"]
        # ER url
        er_url = er_urls.get(normalizar(nombre_proy))

        # Obtener inversionistas del proyecto
        proy_detail = api.get(f"/api/v1/proyectos/{pid}")
        inversionistas_db = proy_detail.get("inversionistas", [])

        print(f"\n→ {nombre_proy} (id={pid}, {len(inv_grupos)} grupos)")

        if dry_run:
            stats["proyectos_ok"] += 1
            continue

        # Crear o localizar la liquidacion
        try:
            liq_resp = api.post("/api/v1/liquidaciones", {
                "proyecto_id": pid,
                "periodo": periodo_date,
                "tipo_venta": "ppa",  # default; puede actualizarse después
                "generado_por_id": usuario_id,
            })
            liq_id = liq_resp["id"]
            print(f"  ✓ Liquidación creada id={liq_id}")
            stats["liq_creadas"] += 1
        except requests.HTTPError as e:
            if e.response.status_code == 422:
                # Ya existe, buscarla
                liqs = api.get("/api/v1/liquidaciones",
                               params={"proyecto_id": pid, "size": 50})
                liq_id = next(
                    (l["id"] for l in liqs["items"] if l["periodo"].startswith(f"{y}-{m.zfill(2)}")),
                    None,
                )
                if not liq_id:
                    print(f"  ✗ No se pudo crear ni encontrar liquidación para {nombre_proy}")
                    continue
                print(f"  ~ Liquidación existente id={liq_id}")
            else:
                raise

        # Actualizar ER url y comprobante si disponibles
        patch_body = {}
        if er_url:
            patch_body["estado_resultados_url"] = er_url
        # Comprobante del Total si existe
        total_rows = inv_grupos.get("Total", [])
        for row in total_rows:
            if row[2].lower() == "información" and row[10].strip():
                patch_body["comprobante_contable_ref"] = row[10].strip()
            # Consecutivos iniciales del Total Información
            if row[2].lower() == "información":
                try:
                    if row[8].strip().isdigit():
                        patch_body["consecutivo_inicial_ingresos"] = int(row[8].strip())
                except (IndexError, ValueError):
                    pass
                try:
                    if len(row) > 9 and row[9].strip().isdigit():
                        patch_body["consecutivo_inicial_costos"] = int(row[9].strip())
                except (IndexError, ValueError):
                    pass
        if patch_body:
            api.patch(f"/api/v1/liquidaciones/{liq_id}", patch_body)

        # Procesar cada grupo de inversionista
        for inv_nombre, filas in inv_grupos.items():
            es_total = inv_nombre.upper() == "TOTAL"

            inv_db = None if es_total else buscar_inversionista(inversionistas_db, inv_nombre)
            inv_id = inv_db["id"] if inv_db else None

            # Extraer consecutivos del row Información de este inversionista
            consecutivo_ing = None
            consecutivo_cos = None
            for row in filas:
                if row[2].lower() == "información":
                    try:
                        v = row[8].strip()
                        if v.isdigit():
                            consecutivo_ing = int(v)
                    except (IndexError, ValueError):
                        pass
                    try:
                        v = row[9].strip() if len(row) > 9 else ""
                        if v.isdigit():
                            consecutivo_cos = int(v)
                    except (IndexError, ValueError):
                        pass

            # Clasificar filas por tipo documento
            filas_mandato_ing = [r for r in filas if r[2].lower() in ("mandato", "buenaventura")]
            filas_mandato_cos = [r for r in filas if r[2].lower() in ("costos",)]
            filas_factura = [r for r in filas if r[2].lower() == "factura"]

            # Crear mandato de ingresos si hay líneas
            lineas_ing = [r for r in filas_mandato_ing
                          if r[5].strip() and r[5].strip().lower() not in ("porcentaje de participación", "valor a pagar")]
            if lineas_ing:
                m_body = {
                    "tipo": "ingresos",
                    "inversionista_id": inv_id,
                    "beneficiario_nombre": inv_nombre if not es_total else None,
                    "consecutivo": consecutivo_ing,
                    "pa_aplica": inv_db.get("es_patrimonio_autonomo", False) if inv_db else False,
                }
                m_resp = api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos", m_body)
                mid = m_resp["id"]
                stats["mandatos"] += 1

                for orden, row in enumerate(filas_mandato_ing):
                    concepto = row[5].strip()
                    if not concepto or concepto.lower() in ("porcentaje de participación",):
                        continue
                    valor = parse_valor(row[6]) if len(row) > 6 else None
                    if valor is None:
                        continue
                    tipo_l = concepto_a_tipo_linea(concepto)
                    ref = row[7].strip() if len(row) > 7 else ""
                    # col 8: puede ser PDF filename o consecutivo
                    soporte_nombre = row[8].strip() if len(row) > 8 else ""
                    linea_body = {
                        "tipo_linea": tipo_l,
                        "concepto": concepto,
                        "valor_cop": valor,
                        "referencia_factura": ref or None,
                        "orden": orden,
                    }
                    if soporte_nombre and not soporte_nombre.isdigit():
                        linea_body["referencia_factura"] = (ref + " | " + soporte_nombre).strip(" | ") or None
                    api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}/lineas", linea_body)
                    stats["lineas"] += 1

                # Actualizar total del mandato
                total_row = next((r for r in filas_mandato_ing
                                  if r[5].strip().lower() == "valor a pagar"), None)
                if total_row:
                    val_net = parse_valor(total_row[6])
                    if val_net is not None:
                        api.patch(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mid}",
                                  {"valor_neto_cop": val_net})

            # Crear mandato de costos si hay líneas
            lineas_cos = [r for r in filas_mandato_cos
                          if r[5].strip() and r[5].strip().lower() not in ("porcentaje de participación", "valor a pagar")]
            if lineas_cos:
                mc_body = {
                    "tipo": "costos",
                    "inversionista_id": inv_id,
                    "beneficiario_nombre": inv_nombre if not es_total else None,
                    "consecutivo": consecutivo_cos,
                    "pa_aplica": inv_db.get("es_patrimonio_autonomo", False) if inv_db else False,
                }
                mc_resp = api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos", mc_body)
                mcid = mc_resp["id"]
                stats["mandatos"] += 1

                for orden, row in enumerate(filas_mandato_cos):
                    concepto = row[5].strip()
                    if not concepto:
                        continue
                    valor = parse_valor(row[6]) if len(row) > 6 else None
                    if valor is None:
                        continue
                    tipo_l = concepto_a_tipo_linea(concepto)
                    ref = row[7].strip() if len(row) > 7 else ""
                    soporte_nombre = row[8].strip() if len(row) > 8 else ""
                    comprobante = row[10].strip() if len(row) > 10 else ""
                    linea_body = {
                        "tipo_linea": tipo_l,
                        "concepto": concepto,
                        "valor_cop": valor,
                        "referencia_factura": ref or None,
                        "orden": orden,
                    }
                    if soporte_nombre and not soporte_nombre.isdigit():
                        linea_body["referencia_factura"] = (ref + " | " + soporte_nombre).strip(" | ") or None
                    api.post(f"/api/v1/liquidaciones/{liq_id}/mandatos/{mcid}/lineas", linea_body)
                    stats["lineas"] += 1

                # También crear LiquidacionCosto para los costos del Total (nivel proyecto)
                if es_total:
                    for row in filas_mandato_cos:
                        concepto = row[5].strip()
                        if not concepto:
                            continue
                        valor = parse_valor(row[6]) if len(row) > 6 else None
                        if valor is None or valor == 0:
                            continue
                        ref = row[7].strip() if len(row) > 7 else ""
                        soporte_nombre = row[8].strip() if len(row) > 8 else ""
                        comprobante = row[10].strip() if len(row) > 10 else ""
                        tipo_costo = _concepto_a_tipo_costo(concepto)
                        costo_body = {
                            "tipo_costo": tipo_costo,
                            "descripcion": concepto,
                            "nro_soporte": ref or comprobante or None,
                            "valor_cop": valor,
                        }
                        if soporte_nombre and not soporte_nombre.isdigit():
                            costo_body["nro_soporte"] = (
                                (costo_body["nro_soporte"] or "") + " | " + soporte_nombre
                            ).strip(" | ") or None
                        api.post(f"/api/v1/liquidaciones/{liq_id}/costos", costo_body)
                        stats["costos"] += 1

            # Crear facturas de servicio (solo para Total, son a nivel proyecto)
            if es_total and filas_factura:
                for row in filas_factura:
                    concepto = row[5].strip()
                    if not concepto:
                        continue
                    valor = parse_valor(row[6]) if len(row) > 6 else None
                    if valor is None:
                        continue
                    tipo_srv = _concepto_a_tipo_factura(concepto)
                    ref = row[7].strip() if len(row) > 7 else ""
                    factura_body = {
                        "tipo_servicio": tipo_srv,
                        "numero_factura": ref or None,
                        "valor_cop": valor,
                    }
                    api.post(f"/api/v1/liquidaciones/{liq_id}/facturas", factura_body)
                    stats["facturas"] += 1

        stats["proyectos_ok"] += 1

    print("\n" + "=" * 50)
    print(f"Proyectos cargados:     {stats['proyectos_ok']}")
    print(f"Liquidaciones creadas:  {stats['liq_creadas']}")
    print(f"Mandatos creados:       {stats['mandatos']}")
    print(f"Líneas creadas:         {stats['lineas']}")
    print(f"Costos creados:         {stats['costos']}")
    print(f"Facturas creadas:       {stats['facturas']}")
    if stats["proyectos_no_match"]:
        print(f"\nSin match en DB ({len(stats['proyectos_no_match'])}):")
        for n in stats["proyectos_no_match"]:
            print(f"  - {n}")


def _concepto_a_tipo_costo(concepto: str) -> str:
    norm = normalizar(concepto)
    if "arriendo" in norm:          return "arriendo"
    if "mantenimiento" in norm:     return "mantenimiento"
    if "internet" in norm:          return "internet"
    if "poliza" in norm or "póliza" in norm: return "polizas"
    if "servicios p" in norm:       return "servicios_publicos"
    if "cambio" in norm and "equipo" in norm: return "cambio_equipos_medida"
    if "comercializaci" in norm:    return "comercializacion_xm"
    return "otro"


def _concepto_a_tipo_factura(concepto: str) -> str:
    norm = normalizar(concepto)
    if "representaci" in norm:  return "representacion"
    if "cgm" in norm:           return "cgm"
    return "administracion_operacion"


def main():
    parser = argparse.ArgumentParser(description="Carga CSV de liquidaciones a la API")
    parser.add_argument("--csv",      required=True, help="Ruta al archivo CSV")
    parser.add_argument("--periodo",  required=True, help="Período YYYY-MM (ej: 2026-01)")
    parser.add_argument("--api-url",  default="https://backend-production-63d8.up.railway.app")
    parser.add_argument("--usuario",  required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dry-run",  action="store_true", help="Solo muestra el mapeo sin crear datos")
    args = parser.parse_args()

    api = APIClient(args.api_url)
    print(f"Autenticando en {args.api_url}...")
    api.login(args.usuario, args.password)
    print("✓ Autenticado")

    cargar_csv(api, args.csv, args.periodo, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
