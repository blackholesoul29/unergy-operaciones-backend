"""
conciliacion_mandatos.py
---------------------------------------------------------------------------
Motor PURO (sin ORM ni framework) de conciliación "Mandato (PDF) vs. Asiento
contable (Odoo .xlsx)" para el Validador de Mandatos → Conciliación Contable →
COSTOS.

Mirror en el backend de `src/utils/conciliacionMandatos.js` del frontend. Recibe
datos ya extraídos (filas del Excel y texto del PDF) y devuelve el resultado de
la conciliación; no lee archivos ni toca la BD.

Reglas clave aprendidas en producción (NO relajar sin revisar):
  1. El mandante se empareja por PALABRA COMPLETA exigiendo TODOS sus términos
     distintivos. Con subcadena, "STRADA" coincide dentro de "E-STRADA" y se
     suman costos de un tercero equivocado.
  2. Mandante, NIT y proyecto se leen del CUERPO del PDF, no del nombre de
     archivo (el nombre puede traer tildes mal codificadas).
  3. Tolerancia de redondeo de $1 al comparar importes.
  4. En arriendo el mandante (la fiduciaria) aparece en AMBOS lados del asiento
     con el MISMO importe; se suma solo el DÉBITO, nunca el neto (debe − haber).
---------------------------------------------------------------------------
"""
from __future__ import annotations

import re
import unicodedata

# ===================== CONFIGURACIÓN (modo COSTOS) =====================

#: Cuenta contable -> concepto del mandato. Ajustar si cambia el PUC.
ACC2CONCEPT: dict[str, str] = {
    "28151002": "mant",     "28151003": "iva_mant",
    "28151009": "int",      "28151015": "int",
    "28151010": "iva_int",  "28151016": "iva_int",
    "28150515": "arr",      "28150517": "arr",
    "28150516": "iva_arr",  "28150518": "iva_arr",
    # Arrendamiento para terceros con arrendador NO responsable de IVA. Cuenta
    # dedicada e inequívoca (nunca lleva IVA) → mapea DIRECTO a arr_cc, sin
    # depender de la etiqueta del asiento (que cambia de redacción cada mes).
    "28151025": "arr_cc",
    # Póliza todo riesgo y lucrocesante (antes sin mapear: el verificador la
    # ignoraba tanto en el asiento como en el mandato).
    "28151004": "poliza",   "28151007": "iva_poliza",
    # Servicios públicos - consumo de energía (sin cuenta de IVA separada; la
    # contrapartida en Haber —p. ej. "23355001 SERV DE ENERGIA"— no es un costo
    # adicional, es solo el otro lado del asiento).
    "28151008": "serv_pub",
    # Administración de proyectos (costos para terceros).
    "28151020": "admin",    "28151021": "iva_admin",
}

#: Concepto -> etiqueta legible.
CONCEPTS: dict[str, str] = {
    "mant": "Mantenimiento", "iva_mant": "IVA mantenimiento",
    "int": "Servicio de internet", "iva_int": "IVA internet",
    "arr": "Arriendo", "iva_arr": "IVA arriendo",
    "poliza": "Póliza todo riesgo y lucrocesante", "iva_poliza": "IVA póliza",
    "serv_pub": "Servicios públicos - consumo de energía",
    "admin": "Administración", "iva_admin": "IVA administración",
    # Sub-tipos de arriendo cuando el proyecto factura por separado (ej. La
    # Reserva). Si el proyecto no divide el arriendo, todo sigue cayendo en el
    # concepto genérico 'arr'.
    "arr_cc": "Arriendo Cuenta de Cobro", "arr_fact": "Arriendo Factura Electrónica",
}

#: Cuentas que NO son de costo de mandato: si reciben débito = "cuenta equivocada".
NON_COST_ACCOUNTS: dict[str, str] = {
    "23355002": "Contrapartida proveedor internet",
    "23359505": "Otros",
    "23653010": "Retención arrendamientos",
    "22050505": "Proveedores nacionales",
    "28151006": "Retefuente terceros",
}

#: Palabras a ignorar al comparar nombres de mandante/asociado.
STOP = {"SA", "SAS", "SAA", "LTDA", "CIA", "ESP", "EN", "DEL", "LOS", "LAS",
        "DE", "LA", "EL", "Y", "S", "A", "SOCIEDAD", "C"}

#: Palabras de relleno al comparar nombres de proyecto/planta.
FILLER = {"MINIGRANJA", "SOLAR", "PROYECTO", "MANDATO", "COSTOS", "COSTO",
          "MINI", "GRANJA", "LA", "EL", "LOS", "LAS", "DE", "DEL", "SAN"}

#: Tolerancia de redondeo en pesos.
TOL = 1


# ===================== UTILIDADES =====================

def norm(s) -> str:
    """Mayúsculas, sin tildes, solo [A-Z0-9 ], espacios colapsados."""
    s = "" if s is None else str(s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def project_tokens(s) -> list[str]:
    return [t for t in norm(s).split(" ") if len(t) > 2 and t not in FILLER]


def expandir_abreviaturas(s) -> str:
    """Expande abreviaturas comunes ANTES de tokenizar. En algunas filas el campo
    "Asociado" del asiento abrevia el mandante con "PA" (Patrimonio Autónomo) en
    vez del nombre completo "PATRIMONIOS AUTONOMOS..." (ej. "FIDUCIARIA BANCOLOMBIA
    PA NESTLE 18254"). Como "PA" tiene solo 2 letras se descartaba por el filtro de
    longitud y nunca calzaba con "PATRIMONIOS"/"AUTONOMOS" del mandato → el mandato
    se reportaba como "no aparece registrado" aunque sí estaba, con otro texto.
    """
    return re.sub(r"\bPA\b", "PATRIMONIOS AUTONOMOS", norm(s))


def name_token_set(s) -> set[str]:
    """Conjunto de tokens distintivos de un nombre de empresa/persona (palabra completa)."""
    return {w for w in expandir_abreviaturas(s).split(" ") if len(w) >= 3 and w not in STOP}


def _strip_money(s):
    """Normaliza un string monetario a cuerpo numérico + signo. None si queda vacío."""
    if s is None:
        return None
    if isinstance(s, bool):  # evita que True/False se traten como números
        return None
    if isinstance(s, (int, float)):
        return {"is_number": True, "value": float(s), "neg": False}
    t = re.sub(r"\s", "", str(s).replace("$", "").strip())
    if not t:
        return None
    neg = bool(re.match(r"^-", t)) or bool(re.match(r"^\(.*\)$", t))
    t = re.sub(r"[()]", "", t)
    t = re.sub(r"^-", "", t)
    if not t:
        return None
    return {"is_number": False, "body": t, "neg": neg}


def normalizar_cifra(s) -> float:
    """Normaliza una CIFRA a float detectando si la coma/punto es miles o decimal.

    Función ÚNICA de parseo numérico; sirve para AMBAS fuentes sin saber el origen:
      - Mandato (PDF), formato US: coma=miles, punto=decimal  ("2,011.51" → 2011.51)
      - Asiento (Excel), formato CO: punto=miles, coma=decimal ("2.011,51" → 2011.51)

    Reglas:
      1. Si ya es número, se devuelve tal cual (así llegan las celdas del xlsx).
      2. Se quitan $ y espacios; negativo por signo "-" o paréntesis "(1.234)".
      3. Si hay coma Y punto: el ÚLTIMO en aparecer es el DECIMAL; el otro, miles.
      4. Un solo tipo de separador:
           - varias veces                      → miles   ("1.234.567"/"1,234,567")
           - una vez con EXACTAMENTE 3 dígitos  → miles   ("497,333"/"129.413")
           - una vez con ≠3 dígitos             → decimal ("0,50"→0.5 / "12.5")
    La regla 4 asume el dominio (pesos): no hay importes de 3 decimales. → 0 si vacío.
    """
    p = _strip_money(s)
    if not p:
        return 0
    if p["is_number"]:
        return p["value"]
    body = p["body"]
    has_comma = "," in body
    has_dot = "." in body
    if has_comma and has_dot:
        coma_es_decimal = body.rfind(",") > body.rfind(".")
        t = body.replace(".", "").replace(",", ".") if coma_es_decimal else body.replace(",", "")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = body.split(sep)
        una_vez = len(parts) == 2
        decimales = len(parts[1]) if una_vez else 0
        t = body.replace(sep, ".") if (una_vez and decimales != 3) else "".join(parts)
    else:
        t = body
    try:
        n = float(t)
    except ValueError:
        return 0
    return -n if p["neg"] else n


# @deprecated: usar normalizar_cifra. Alias por compatibilidad; delegan en la única función.
parse_mandato_number = normalizar_cifra
parse_asiento_number = normalizar_cifra


# ===================== PARSEO DE ASIENTOS (Excel Odoo) =====================

def parse_asientos(rows) -> dict:
    """Detecta columnas por nombre de encabezado (robusto a variaciones del export).

    :param rows: filas del Excel incluida la cabecera (lista de listas).
    :returns: {"details": [...], "tags": [...]} donde details es
        [{cpt, asociado, acc, accDesc, debe, haber, etiqueta, proj}] y tags son
        las etiquetas analíticas (proyectos) únicas, ordenadas.
    """
    if not rows:
        return {"details": [], "tags": []}
    head = [norm(h) for h in rows[0]]

    def find(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return -1

    def find_inc(sub):
        for i, h in enumerate(head):
            if sub in h:
                return i
        return -1

    col = {
        "asiento": find("ASIENTO CONTABLE", "ASIENTO"),
        "asociado": find("ASOCIADO"),
        "cuenta": find("CUENTA"),
        "debe": find("DEBE"),
        "haber": find("HABER"),
        "importe": find_inc("IMPORTE"),
        "etiqueta": find("ETIQUETA"),
        "proj": find_inc("ANALITICA"),
    }

    def cell(r, i):
        return r[i] if 0 <= i < len(r) else None

    details = []
    tag_set: set[str] = set()
    for r in rows[1:]:
        if not r:
            continue
        asociado = cell(r, col["asociado"]) if col["asociado"] != -1 else None
        cuenta = cell(r, col["cuenta"]) if col["cuenta"] != -1 else None
        if not asociado or not cuenta:
            continue  # solo líneas de detalle
        # Saltar filas de agrupación/subtotal (asiento con sangría) si hay columna asiento
        if col["asiento"] != -1:
            a = cell(r, col["asiento"])
            if a is not None and re.match(r"^\s", str(a)):
                continue
        acc_no = str(cuenta).strip().split()[0]
        acc_desc = str(cuenta).strip().replace(acc_no, "").strip()

        # Débito/haber: usar DEBE/HABER si existen; si no, derivar del importe con signo.
        debe = haber = 0
        if col["debe"] != -1 or col["haber"] != -1:
            debe = parse_asiento_number(cell(r, col["debe"]))
            haber = parse_asiento_number(cell(r, col["haber"]))
        elif col["importe"] != -1:
            imp = parse_asiento_number(cell(r, col["importe"]))
            if imp >= 0:
                debe = imp
            else:
                haber = -imp

        etiqueta = str(cell(r, col["etiqueta"]) or "") if col["etiqueta"] != -1 else ""
        proj_raw = cell(r, col["proj"]) if col["proj"] != -1 else etiqueta
        proj = str(proj_raw or "").strip()
        if proj:
            tag_set.add(proj)

        details.append({
            "cpt": str(cell(r, col["asiento"]) or "") if col["asiento"] != -1 else "",
            "asociado": str(asociado),
            "acc": acc_no, "accDesc": acc_desc,
            "debe": debe, "haber": haber,
            "etiqueta": etiqueta,
            "proj": proj,
        })
    return {"details": details, "tags": sorted(tag_set)}


# ===================== PARSEO DE MANDATO (texto del PDF) =====================

#: Etiqueta del PDF -> concepto. El ORDEN importa: las reglas específicas se
#: evalúan antes que las genéricas (startswith), para que "ARRIENDO CUENTA DE
#: COBRO" no caiga en 'arr'.
_MANDATO_CONCEPT_MAP = [
    ("MANTENIMIENTO", "mant"), ("IVA MANTENIMIENTO", "iva_mant"),
    ("SERVICIO DE INTERNET", "int"), ("IVA INTERNET", "iva_int"),
    # Variantes específicas de arriendo ANTES del genérico: cuando el proyecto
    # divide el arriendo en dos facturas (ej. La Reserva), se guardan como
    # conceptos separados y cada una se verifica contra su etiqueta del asiento.
    ("ARRIENDO CUENTA DE COBRO", "arr_cc"), ("ARRIENDO FACTURA", "arr_fact"),
    # Redacción nueva del mandato (desde jul-2026): distingue por responsabilidad
    # de IVA del arrendador en vez de por tipo de soporte (CC/Factura). Debe ir
    # ANTES del genérico "ARRIENDO": si no, el genérico la captura y la cae el
    # chequeo "contiene IVA" de más abajo, descartando el valor por completo.
    ("ARRIENDO NO RESPONSABLE DE IVA", "arr_cc"), ("ARRIENDO RESPONSABLE DE IVA", "arr_fact"),
    ("ARRIENDO", "arr"), ("IVA ARRIENDO", "iva_arr"),
    # 'POLIZA' (sin el resto de la frase) para tolerar variaciones de redacción.
    ("POLIZA", "poliza"), ("IVA POLIZA", "iva_poliza"),
    # Servicios públicos - consumo de energía (sin IVA separado).
    ("SERVICIOS PUBLICOS", "serv_pub"),
    # Administración de proyectos.
    ("ADMINISTRACION", "admin"), ("IVA ADMINISTRACION", "iva_admin"),
]

_LINEA_VALOR_RE = re.compile(r"^(.*?)\$\s*([\d.,]+)\s*$")


def extract_mandate(text: str, filename: str = "") -> dict:
    """
    :param text: texto extraído del PDF.
    :param filename: nombre del archivo (fallback).
    :returns: {cmu, projName, mandante, nit, vals, total}
    """
    text = text or ""
    m_cmu = re.search(r"CMU\d+", text, re.I) or re.search(r"CMU\d+", filename, re.I)
    cmu = m_cmu.group(0) if m_cmu else "?"
    flat = re.sub(r"\s+", " ", text)

    # Mandante + NIT desde el cuerpo (más confiable que el nombre de archivo)
    mandante, nit = "", ""
    mm = re.search(
        r"de mandatario,?\s*y\s+(.+?),\s*con NIT\.?\s*([\d.\-\s]+?),?\s*en calidad de mandante",
        flat, re.I)
    if mm:
        mandante = mm.group(1).strip()
        nit = re.sub(r"\s", "", mm.group(2))
    if not mandante:
        fm = re.search(r"-([^-]+)\.pdf$", filename, re.I)
        mandante = fm.group(1) if fm else ""

    # Proyecto / planta
    proj = None
    for rx, flags, src in (
        (r"relacionado con el proyecto\s+([^.]+?)\s*$", re.I, flat),
        (r"relacionado con el proyecto\s+(.+?)(?:\.|\s+a saber)", re.I, flat),
        (r"proyecto\s+(.+?)\s+a saber", re.I | re.S, text),
    ):
        if proj:
            break
        mp = re.search(rx, src, flags)
        if mp:
            proj = mp.group(1)
    if not proj:
        mf = re.search(r"-Costos-(.+?)-[^-]+\.pdf", filename, re.I)
        proj = mf.group(1) if mf else filename
    proj = re.sub(r"\s+", " ", proj or "").strip()

    # Conceptos: línea "ETIQUETA ... $ valor"
    vals: dict[str, float] = {}
    total = None
    for line in text.split("\n"):
        m = _LINEA_VALOR_RE.match(line)
        if not m:
            continue
        label = norm(m.group(1))
        v = parse_mandato_number(m.group(2))
        if "VALOR A PAGAR" in label:
            total = v
            continue
        for kw, key in _MANDATO_CONCEPT_MAP:
            if label.startswith(kw) or (kw.startswith("IVA") and kw in label):
                # Evita que "IVA MANTENIMIENTO"/"IVA PÓLIZA"/... caiga en el concepto base.
                if key in ("mant", "int", "arr", "poliza", "admin") and "IVA" in label:
                    continue
                # Se ACUMULA (no se sobrescribe) para soportar conceptos que el
                # mandato divide en varias líneas mapeadas al mismo concepto
                # genérico (ej. dos líneas de "arriendo"); antes la segunda pisaba
                # a la primera.
                vals[key] = vals.get(key, 0) + v
                break
    return {"cmu": cmu, "projName": proj, "mandante": mandante, "nit": nit,
            "vals": vals, "total": total}


# ===================== EMPAREJAMIENTO DE PROYECTO =====================

def suggest_tag(proj_name: str, tags: list[str], saved_map: dict | None = None) -> dict:
    """Sugiere la etiqueta analítica para un mandato. Prioriza un mapa guardado
    (nombre normalizado → etiqueta), luego automático por token.
    :returns: {tag, status, candidates} status: 'recordado'|'auto'|'elige'|'revisar'
    """
    saved_map = saved_map or {}
    remembered = saved_map.get(norm(proj_name))
    if remembered and remembered in tags:
        return {"tag": remembered, "status": "recordado", "candidates": []}

    tks = project_tokens(proj_name)
    if not tks:
        return {"tag": "", "status": "revisar", "candidates": []}
    cand = [t for t in tags if any(tk in norm(t) for tk in tks)]
    if len(cand) == 1:
        return {"tag": cand[0], "status": "auto", "candidates": cand}
    if len(cand) > 1:
        scored = sorted(
            ({"t": t, "sc": sum(1 for tk in tks if tk in norm(t))
              + (0.5 if norm(t).endswith(tks[-1]) else 0)} for t in cand),
            key=lambda x: x["sc"], reverse=True)
        if scored[0]["sc"] > scored[1]["sc"]:
            return {"tag": scored[0]["t"], "status": "auto", "candidates": cand}
        return {"tag": "", "status": "elige", "candidates": cand}
    return {"tag": "", "status": "revisar", "candidates": []}


# ===================== CONCILIACIÓN =====================

def fmt(n) -> str:
    try:
        n = round(float(n or 0))
    except (TypeError, ValueError):
        n = 0
    return f"{n:,}".replace(",", ".")


def reconciliar(mandato: dict, details: list[dict], tag: str) -> dict:
    """Concilia un mandato contra el detalle contable.

    :param mandato: resultado de extract_mandate().
    :param details: details de parse_asientos().
    :param tag: etiqueta analítica elegida/confirmada.
    :returns: {status, flags, sums, lines}
    """
    flags = []
    if not tag:
        return {"status": "bad",
                "flags": [{"lvl": "bad", "code": "SIN_TAG",
                           "txt": "No se asignó etiqueta analítica; no se puede verificar."}],
                "sums": {}, "lines": []}

    # Mandante por PALABRA COMPLETA (fix STRADA/ESTRADA) pero tolerando abreviaturas.
    mand_tok = name_token_set(mandato.get("mandante"))

    def asociado_match(aso):
        # Coincide si uno de los nombres es SUBCONJUNTO del otro. El asiento suele
        # abreviar el mandante omitiendo las palabras corporativas — p. ej.
        # "PA 17844 SOL DE LA SIERRA" vs. el mandante completo "PATRIMONIOS
        # AUTONOMOS FIDUCIARIA BANCOLOMBIA ... 17844 SOL DE LA SIERRA": comparten
        # patrimonio + fondo pero el asiento no trae FIDUCIARIA/BANCOLOMBIA. Exigir
        # TODOS los tokens del mandante fallaba (0 líneas). Se exige que TODOS los
        # tokens del conjunto MÁS PEQUEÑO estén en el otro, con intersección no
        # vacía. NO reintroduce STRADA⊂ESTRADA: por palabra completa STRADA y
        # ESTRADA no comparten ningún token.
        aset = name_token_set(aso)
        if not mand_tok or not aset:
            return False
        inter = len(mand_tok & aset)
        return inter > 0 and (inter == len(mand_tok) or inter == len(aset))

    tag_lines = [d for d in details if d["proj"] == tag]
    lines = [d for d in tag_lines if asociado_match(d["asociado"])]
    matched_ids = {id(d) for d in lines}
    # Líneas del mismo proyecto que quedaron FUERA de `lines` (cuenta no mapeada
    # al concepto esperado, o asociado que no calza con el mandante — p. ej. el
    # mantenimiento pagado directo al contratista vía "Administración de
    # proyectos" con el contratista como Asociado, en vez de la fiduciaria).
    unmatched_lines = [d for d in tag_lines if id(d) not in matched_ids]

    # Sumar por concepto el DÉBITO de la cuenta de costo (NUNCA el neto debe − haber).
    sums: dict[str, float] = {}
    wrong_acc = []
    for d in lines:
        c = ACC2CONCEPT.get(d["acc"])
        # Si la cuenta es de arriendo genérico, se afina el concepto según la
        # ETIQUETA del asiento — algunos proyectos (ej. La Reserva) dividen el
        # arriendo en dos facturas que comparten cuenta contable pero se
        # distinguen por la etiqueta: "...CC..." (Cuenta de Cobro) o "...FACT..."
        # (Factura). Si la etiqueta no trae ninguna, se queda como 'arr' genérico
        # y no rompe los proyectos que no dividen el arriendo.
        if c == "arr":
            etq = norm(d.get("etiqueta") or "")
            if re.search(r"\bCC\b", etq):
                c = "arr_cc"
            elif re.search(r"\bFACT\b", etq):
                c = "arr_fact"
        if c:
            sums[c] = sums.get(c, 0) + d["debe"]
        elif d["acc"] in NON_COST_ACCOUNTS and (d["debe"] - d["haber"]) > 0:
            wrong_acc.append(d)

    vals = mandato.get("vals") or {}

    # A) Importes por concepto (incluye faltantes)
    for c in vals:
        mv = vals[c] or 0
        av = round((sums.get(c, 0)) * 100) / 100
        if av == 0 and mv > 0:
            candidatos = [d for d in unmatched_lines if abs(d["debe"] - mv) <= TOL]
            if candidatos:
                best = min(candidatos, key=lambda d: abs(d["debe"] - mv))
                flags.append({"lvl": "warn", "code": "OTRA_CUENTA",
                              "txt": f"{CONCEPTS[c]}: en el mandato ({fmt(mv)}) — registrado en el asiento pero en otra cuenta/asociado: "
                                     f"cuenta {best['acc']} ({best['accDesc']}), asociado \"{best['asociado']}\" ({fmt(best['debe'])})."})
            else:
                flags.append({"lvl": "bad", "code": "FALTANTE",
                              "txt": f"{CONCEPTS[c]}: en el mandato ({fmt(mv)}) pero no aparece en el asiento para este mandante/proyecto."})
        elif abs(mv - av) > TOL:
            flags.append({"lvl": "bad", "code": "DIFERENCIA",
                          "txt": f"{CONCEPTS[c]}: mandato {fmt(mv)} vs. asiento {fmt(av)} · diferencia {fmt(abs(mv - av))}."})
        else:
            flags.append({"lvl": "ok", "code": "OK",
                          "txt": f"{CONCEPTS[c]}: {fmt(mv)} — coincide."})

    # B) Conceptos en el asiento que el mandato no lista (sobrantes)
    for c in sums:
        if c not in vals and sums[c] > TOL:
            flags.append({"lvl": "warn", "code": "SOBRANTE",
                          "txt": f"{CONCEPTS[c]}: {fmt(sums[c])} registrado en el asiento pero no listado en el mandato."})

    # C) Cuenta equivocada
    for d in wrong_acc:
        flags.append({"lvl": "bad", "code": "CUENTA",
                      "txt": f"Posible cuenta equivocada: {fmt(d['debe'])} en cuenta {d['acc']} ({NON_COST_ACCOUNTS[d['acc']]}), que no es de costo de mandato."})

    # D) Total declarado vs. suma de costos
    if mandato.get("total") is not None:
        sum_conc = sum(sums.values())
        if abs(sum_conc - mandato["total"]) > TOL:
            flags.append({"lvl": "warn", "code": "TOTAL",
                          "txt": f"Total: \"valor a pagar\" del mandato {fmt(mandato['total'])} vs. suma de costos {fmt(round(sum_conc))}."})

    status = "bad" if any(f["lvl"] == "bad" for f in flags) \
        else "warn" if any(f["lvl"] == "warn" for f in flags) else "ok"
    return {"status": status, "flags": flags, "sums": sums, "lines": lines}
