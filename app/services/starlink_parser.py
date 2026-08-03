"""
Parser de facturas PDF de Starlink Colombia.

Estrategia (igual al script starlink_pdf_a_excel.py):
  - extract_words() con coordenadas X,Y de cada palabra
  - Columna '#' detectada por x0 < 15
  - Columna 'Cant.' por x0 en 405–435
  - Valores COP por formato ^\d[\d.]+,\d{2}$
  - Cada ítem = fila con '#' + TODAS las filas siguientes hasta el
    próximo '#' (necesario porque ítems de 500 GB tienen precios en 2 filas)
  - COP values se acumulan de TODAS las filas del ítem y se ordenan por X
    para garantizar [precio, impuestos, monto] correcto
  - Nombre del sitio = última línea del grupo con 'KIT'
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, TypedDict


# ── Splits 50/50 ──────────────────────────────────────────────────────────────
SPLITS: dict[str, tuple[str, str]] = {
    "JOROPO MAPALE":              ("Joropo",     "Mapale"),
    "CACICA Y PILONERAS":         ("Cacica",     "Piloneras"),
    "LA CACICA Y PILONERAS":      ("Cacica",     "Piloneras"),
    "PAZ VALLENATA Y LEYENDA":    ("Vallenata",  "Leyenda"),
    "LA PAZ VALLENATA Y LEYENDA": ("Vallenata",  "Leyenda"),
    "PUYA Y MERENGUE":            ("Puya",       "Merengue"),
    "VALENCIA OR":                ("Valencia 1", "Valencia 2"),
    "GANDALF Y CANAHUATE":        ("Gandalf",    "Cañahuate"),
    "GANDALF Y CAÑAHUATE":        ("Gandalf",    "Cañahuate"),
    "CHIMA 1 Y 2":                ("Chima 1",    "Chima 2"),
    "CHIMÁ 1 Y 2":                ("Chima 1",    "Chima 2"),
}

# Posiciones X de columnas en el PDF
_X_NUM_MAX  = 15     # columna '#'  (los números de ítem están en x0 ≈ 1)
_X_CANT_MIN = 405    # columna 'Cant.' (x ≈ 417)
_X_CANT_MAX = 435


class ItemDetalle(TypedDict):
    tipo:            Literal["servicio", "adicionales"]
    descripcion:     str
    precio_unitario: float
    cantidad:        int
    total_impuestos: float
    monto_total:     float
    sin_iva:         float
    iva:             float


class ItemAgrupado(TypedDict):
    descripcion:              str
    cantidad_total:           int
    precio_unitario_promedio: float
    sin_iva:                  float
    iva:                      float
    monto_total:              float


class ResultadoStarlink(TypedDict):
    items:          list[ItemDetalle]
    agrupado:       list[ItemAgrupado]
    cargos_totales: float
    suma_items:     float
    coincide:       bool | None
    advertencia:    str | None
    periodo:        str | None          # 'YYYY-MM' extraído de la fecha de factura


# ── Helpers ───────────────────────────────────────────────────────────────────

def _round2(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _limpiar_cop(s: str) -> float:
    """'70.588,00' → 70588.0"""
    return float(s.replace(".", "").replace(",", "."))

def _es_cop(s: str) -> bool:
    """Reconoce montos COP con formato colombiano: 70.588,00 / 294.118,00"""
    return bool(re.match(r"^\d[\d.]*,\d{2}$", s))

def _limpiar_descripcion(s: str) -> str:
    """'AGUSTÍN CODAZZI S2 KIT404472730CZX, KIT...' → 'AGUSTÍN CODAZZI S2'"""
    s = re.sub(r",?\s*KIT\S+", "", s, flags=re.IGNORECASE)
    return " ".join(s.split())

def _sin_iva(monto: float) -> float:
    return _round2(monto / 1.19)

def _iva(monto: float) -> float:
    return _round2(monto - _sin_iva(monto))

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

def _extraer_periodo(texto_pag1: str) -> str | None:
    """Extrae 'YYYY-MM' de 'Fecha de Factura: ..., DD de MMMM de YYYY'."""
    m = re.search(
        r"Fecha de Factura[:\s]+[^,\n]+,?\s*\d{1,2}\s+de\s+(\w+)\s+de\s+(\d{4})",
        texto_pag1, re.IGNORECASE
    )
    if m:
        mes_str = m.group(1).lower()
        año     = m.group(2)
        mes_num = _MESES_ES.get(mes_str)
        if mes_num:
            return f"{año}-{mes_num:02d}"
    return None


def _fmt(v: float) -> str:
    return f"COP {v:,.0f}"


# ── Parser principal ──────────────────────────────────────────────────────────

def parsear_pdf(pdf_bytes: bytes) -> ResultadoStarlink:
    import pdfplumber

    items:          list[ItemDetalle] = []
    cargos_totales: float             = 0.0
    periodo_str:    str | None        = None
    tipo_actual:    str | None        = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # Buffer del ítem en construcción
        # cop_with_x: list of (x_position, value) para ordenar correctamente
        current: dict | None = None

        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words()
            if not words:
                continue

            texto = " ".join(w["text"] for w in words)

            # ── Página 1: solo Cargos totales ──────────────────────────────
            if page_idx == 0:
                # "Cargos totales COP 9.632.022,00"
                m = re.search(
                    r"Cargos\s+totales\s+(?:COP\s+)?([\d.,]+)",
                    texto, re.IGNORECASE
                )
                if m:
                    cargos_totales = _limpiar_cop(m.group(1))
                # Extraer período de "Fecha de Factura: ..., DD de MMMM de YYYY"
                periodo_str = _extraer_periodo(texto)
                continue

            # Activar solo desde la primera página de detalle
            if "Líneas de servicio" in texto and tipo_actual is None:
                tipo_actual = "servicio"
            if tipo_actual is None:
                continue

            # ── Agrupar palabras por Y redondeada ──────────────────────────
            filas: dict[int, list] = defaultdict(list)
            for w in words:
                filas[round(w["top"], 0)].append(w)
            tops = sorted(filas.keys())

            # Detectar inicio de sección 'Líneas adicionales' en esta página
            adicionales_y: int | None = None
            for top in tops:
                row_txt = " ".join(w["text"] for w in filas[top])
                if "Líneas" in row_txt and "adicionales" in row_txt:
                    adicionales_y = top
                    break

            for top in tops:
                fila = filas[top]

                # Sección según posición Y
                sec = (
                    "adicionales"
                    if adicionales_y is not None and top >= adicionales_y
                    else tipo_actual or "servicio"
                )

                # ── ¿Fila con número de ítem '#' en columna izquierda? ──────
                num_ws = [
                    w for w in fila
                    if w["x0"] < _X_NUM_MAX and re.match(r"^\d+$", w["text"])
                ]

                if num_ws:
                    # Guardar ítem anterior (si existe y es válido)
                    if current is not None:
                        item = _construir_item(current)
                        if item:
                            items.append(item)

                    # Cantidad en columna Cant.
                    cant_ws = [
                        w for w in fila
                        if _X_CANT_MIN < w["x0"] < _X_CANT_MAX
                        and re.match(r"^\d+$", w["text"])
                    ]
                    cantidad = int(cant_ws[0]["text"]) if cant_ws else 1

                    # COP values DE ESTA FILA (solo los numéricos, no "COP" label)
                    cops_fila = [
                        (w["x0"], _limpiar_cop(w["text"]))
                        for w in fila
                        if _es_cop(w["text"])
                    ]

                    current = {
                        "tipo":       sec,
                        "cantidad":   cantidad,
                        "cop_with_x": cops_fila,   # (x, valor) — se amplía en continuaciones
                        "site_line":  None,
                    }

                elif current is not None:
                    # ── Fila de continuación del ítem actual ─────────────────
                    row_txt = " ".join(
                        w["text"] for w in sorted(fila, key=lambda x: x["x0"])
                    ).strip()

                    if not row_txt:
                        continue

                    # Acumular COP values (con su x) — necesario para ítems
                    # de 500 GB cuyo precio está en una fila distinta al '#'
                    for w in fila:
                        if _es_cop(w["text"]):
                            current["cop_with_x"].append((w["x0"], _limpiar_cop(w["text"])))

                    # Detectar línea con nombre del sitio (tiene 'KIT')
                    if "KIT" in row_txt:
                        current["site_line"] = row_txt

                # (Las filas antes del primer '#' se ignoran → current=None)

        # Cerrar el último ítem
        if current is not None:
            item = _construir_item(current)
            if item:
                items.append(item)

    suma = _round2(sum(i["monto_total"] for i in items))
    coincide: bool | None   = None
    advertencia: str | None = None

    if cargos_totales > 0:
        diff     = abs(suma - cargos_totales)
        coincide = diff < 2.0
        if not coincide:
            advertencia = (
                f"La suma de ítems ({_fmt(suma)}) no coincide con "
                f"'Cargos totales' del PDF ({_fmt(cargos_totales)}). "
                f"Diferencia: {_fmt(diff)}. Revisa los datos antes de continuar."
            )

    return {
        "items":          items,
        "agrupado":       _construir_agrupado(items),
        "cargos_totales": cargos_totales,
        "suma_items":     suma,
        "coincide":       coincide,
        "advertencia":    advertencia,
        "periodo":        periodo_str,
    }


def _construir_item(buf: dict) -> ItemDetalle | None:
    """
    Convierte el buffer acumulado en ItemDetalle.
    Los COP values se ordenan por X para garantizar [precio, impuestos, monto].
    """
    # Ordenar por X → [precio_unitario, total_impuestos, monto_total]
    cops_sorted = sorted(buf.get("cop_with_x", []), key=lambda t: t[0])
    cops        = [t[1] for t in cops_sorted]

    if len(cops) < 2:
        return None

    monto     = cops[-1]
    impuestos = cops[-2] if len(cops) >= 2 else 0.0
    precio    = cops[-3] if len(cops) >= 3 else cops[0]

    site_raw    = buf.get("site_line") or ""
    descripcion = _limpiar_descripcion(site_raw)
    if not descripcion:
        return None

    return {
        "tipo":            buf["tipo"],
        "descripcion":     descripcion,
        "precio_unitario": precio,
        "cantidad":        buf["cantidad"],
        "total_impuestos": impuestos,
        "monto_total":     monto,
        "sin_iva":         _sin_iva(monto),
        "iva":             _iva(monto),
    }


# ── Tabla Agrupado ────────────────────────────────────────────────────────────

def _match_split(descripcion: str) -> tuple[str, str] | None:
    desc_up = descripcion.upper()
    for key, pair in SPLITS.items():
        if key.upper() in desc_up:
            return pair
    return None


def _construir_agrupado(items: list[ItemDetalle]) -> list[ItemAgrupado]:
    expandidos: list[tuple[str, dict]] = []
    for item in items:
        pair = _match_split(item["descripcion"])
        if pair:
            for nombre in pair:
                expandidos.append((nombre, {
                    **item,
                    "monto_total":     _round2(item["monto_total"]     / 2),
                    "sin_iva":         _round2(item["sin_iva"]         / 2),
                    "iva":             _round2(item["iva"]             / 2),
                    "total_impuestos": _round2(item["total_impuestos"] / 2),
                }))
        else:
            expandidos.append((item["descripcion"], item))

    grupos: dict[str, dict] = {}
    for nombre, it in expandidos:
        if nombre not in grupos:
            grupos[nombre] = {
                "descripcion": nombre,
                "cant_sum":    0,
                "precio_sum":  0.0,
                "precio_cnt":  0,
                "sin_iva":     0.0,
                "iva":         0.0,
                "monto":       0.0,
            }
        g = grupos[nombre]
        g["cant_sum"]   += it["cantidad"]
        g["precio_sum"] += it["precio_unitario"]
        g["precio_cnt"] += 1
        g["sin_iva"]    += it["sin_iva"]
        g["iva"]        += it["iva"]
        g["monto"]      += it["monto_total"]

    result: list[ItemAgrupado] = []
    for nombre in sorted(grupos, key=str.upper):
        g = grupos[nombre]
        result.append({
            "descripcion":              g["descripcion"],
            "cantidad_total":           g["cant_sum"],
            "precio_unitario_promedio": _round2(g["precio_sum"] / g["precio_cnt"]),
            "sin_iva":                  _round2(g["sin_iva"]),
            "iva":                      _round2(g["iva"]),
            "monto_total":              _round2(g["monto"]),
        })
    return result
