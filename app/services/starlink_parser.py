"""
Parser de facturas PDF de Starlink Colombia.

Extrae ítems de las páginas de detalle (ignora el resumen de la página 1).
Secciones reconocidas: "Líneas de servicio" y "Líneas adicionales".
"""
from __future__ import annotations
import io
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict, Literal


# ── Splits 50/50 ──────────────────────────────────────────────────────────────
# Clave: fragmento a buscar en la descripción (case-insensitive)
# Valor: (nombre_proyecto_1, nombre_proyecto_2)
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
}


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


# ── Helpers numéricos ─────────────────────────────────────────────────────────

def _round2(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _parsear_monto(s: str) -> float:
    """'$1.234.567,89'  →  1234567.89"""
    s = s.strip().lstrip("$").replace("\xa0", "").replace(" ", "")
    # Formato colombiano: punto = miles, coma = decimal
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _limpiar_descripcion(raw: str) -> str:
    """Elimina códigos KIT y espacios extras."""
    cleaned = re.sub(r"\s*KIT[A-Z0-9]{6,}\s*", " ", raw, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _sin_iva(monto: float) -> float:
    return _round2(monto / 1.19)


def _iva(monto: float) -> float:
    return _round2(monto - _sin_iva(monto))


# ── Parser principal ─────────────────────────────────────────────────────────

# Regex para detectar una o más columnas numéricas al final de la línea
# Captura los últimos 4 grupos numéricos (precio_unit, cantidad, impuestos, total)
_RE_FILA_4 = re.compile(
    r"^(.+?)\s+"                           # descripcion (lazy)
    r"\$?([\d.,]+)\s+"                     # precio_unitario
    r"(\d+)\s+"                            # cantidad
    r"\$?([\d.,]+)\s+"                     # total_impuestos
    r"\$?([\d.,]+)\s*$",                   # monto_total
)

# Fallback: solo 2 columnas al final (impuestos + total)
_RE_FILA_2 = re.compile(
    r"^(.+?)\s+"
    r"\$?([\d.,]+)\s+"
    r"\$?([\d.,]+)\s*$",
)

_RE_MONTO_FINAL = re.compile(r"\$[\d.,]+$")


def _parsear_linea(line: str, tipo: str) -> ItemDetalle | None:
    """Intenta extraer un ítem de una línea de texto."""
    m = _RE_FILA_4.match(line)
    if m:
        desc       = _limpiar_descripcion(m.group(1))
        precio     = _parsear_monto(m.group(2))
        cantidad   = int(m.group(3))
        impuestos  = _parsear_monto(m.group(4))
        total      = _parsear_monto(m.group(5))
        s_iva      = _sin_iva(total)
        return {
            "tipo":            tipo,
            "descripcion":     desc,
            "precio_unitario": precio,
            "cantidad":        cantidad,
            "total_impuestos": impuestos,
            "monto_total":     total,
            "sin_iva":         s_iva,
            "iva":             _iva(total),
        }
    return None


def parsear_pdf(pdf_bytes: bytes) -> ResultadoStarlink:
    """
    Abre el PDF y extrae todos los ítems de las páginas de detalle.
    """
    import pdfplumber

    items: list[ItemDetalle] = []
    cargos_totales: float = 0.0
    tipo_actual: str | None = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):

            # ── Página 1: solo capturar Cargos totales ──────────────────────
            if page_idx == 0:
                text = page.extract_text() or ""
                m = re.search(
                    r"Cargos?\s+totales?\s*\$?\s*([\d.,]+)",
                    text, re.IGNORECASE
                )
                if m:
                    cargos_totales = _parsear_monto(m.group(1))
                continue

            # ── Páginas de detalle ───────────────────────────────────────────
            # Intentar primero con tablas estructuradas de pdfplumber
            tables = page.extract_tables()
            if tables:
                texto_pagina = page.extract_text() or ""
                # Detectar sección activa por el texto de la página
                if re.search(r"L[ií]neas?\s+adicionales?", texto_pagina, re.IGNORECASE):
                    tipo_pagina = "adicionales"
                elif re.search(r"L[ií]neas?\s+de\s+servicio", texto_pagina, re.IGNORECASE):
                    tipo_pagina = "servicio"
                else:
                    tipo_pagina = tipo_actual or "servicio"

                for table in tables:
                    for row in table:
                        if not row or not any(row):
                            continue
                        cells = [c.strip() if c else "" for c in row]
                        # Ignorar cabeceras
                        if any(re.search(r"descripci[oó]n|precio|cantidad|total|impuesto", c, re.IGNORECASE)
                               for c in cells if c):
                            continue
                        item = _parsear_fila_tabla(cells, tipo_pagina)
                        if item:
                            items.append(item)
            else:
                # Fallback: parseo línea a línea
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if re.search(r"L[ií]neas?\s+de\s+servicio", line, re.IGNORECASE):
                        tipo_actual = "servicio"
                        continue
                    if re.search(r"L[ií]neas?\s+adicionales?", line, re.IGNORECASE):
                        tipo_actual = "adicionales"
                        continue
                    if tipo_actual and _RE_MONTO_FINAL.search(line):
                        item = _parsear_linea(line, tipo_actual)
                        if item:
                            items.append(item)

    suma = _round2(sum(it["monto_total"] for it in items))
    coincide: bool | None = None
    advertencia: str | None = None
    if cargos_totales > 0:
        diff = abs(suma - cargos_totales)
        coincide = diff < 1.0
        if not coincide:
            advertencia = (
                f"La suma de ítems (${suma:,.2f}) no coincide con "
                f"'Cargos totales' del PDF (${cargos_totales:,.2f}). "
                f"Diferencia: ${diff:,.2f}. Verifica los datos antes de continuar."
            )

    agrupado = _construir_agrupado(items)

    return {
        "items":          items,
        "agrupado":       agrupado,
        "cargos_totales": cargos_totales,
        "suma_items":     suma,
        "coincide":       coincide,
        "advertencia":    advertencia,
    }


def _parsear_fila_tabla(cells: list[str], tipo: str) -> ItemDetalle | None:
    """Parsea una fila de tabla extraída por pdfplumber."""
    # Filtrar celdas vacías para detectar columnas útiles
    non_empty = [c for c in cells if c]
    if len(non_empty) < 3:
        return None
    # La primera celda no vacía es la descripción, las últimas son números
    desc_raw = non_empty[0]
    # Intentar extraer los 3-4 últimos valores como montos
    montos = []
    for c in non_empty[1:]:
        v = _parsear_monto(c)
        if v > 0:
            montos.append(v)
    if len(montos) < 2:
        return None

    desc = _limpiar_descripcion(desc_raw)
    if not desc or re.match(r"^\d+$", desc):
        return None

    total = montos[-1]
    impuestos = montos[-2] if len(montos) >= 2 else 0.0
    precio = montos[0] if len(montos) >= 3 else total
    cantidad = 1
    # Intentar detectar cantidad (entero pequeño entre descripción y montos)
    for c in non_empty[1:]:
        try:
            v = int(c)
            if 1 <= v <= 100:
                cantidad = v
                break
        except ValueError:
            pass

    return {
        "tipo":            tipo,
        "descripcion":     desc,
        "precio_unitario": precio,
        "cantidad":        cantidad,
        "total_impuestos": impuestos,
        "monto_total":     total,
        "sin_iva":         _sin_iva(total),
        "iva":             _iva(total),
    }


# ── Construcción de tabla Agrupado ────────────────────────────────────────────

def _match_split(descripcion: str) -> tuple[str, str] | None:
    """Devuelve (nombre1, nombre2) si aplica división 50/50, None si no."""
    desc_upper = descripcion.upper()
    for key, pair in SPLITS.items():
        if key.upper() in desc_upper:
            return pair
    return None


def _construir_agrupado(items: list[ItemDetalle]) -> list[ItemAgrupado]:
    """
    Construye la tabla agrupada aplicando divisiones 50/50 y sumando
    ítems del mismo sitio.
    """
    # Primero expandir los splits
    expandidos: list[tuple[str, ItemDetalle]] = []
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
                    # precio_unitario_promedio se calcula al agrupar
                }))
        else:
            expandidos.append((item["descripcion"], item))

    # Agrupar por nombre de sitio
    grupos: dict[str, dict] = {}
    for nombre, it in expandidos:
        if nombre not in grupos:
            grupos[nombre] = {
                "descripcion":  nombre,
                "cantidad_sum": 0,
                "precio_sum":   0.0,
                "precio_count": 0,
                "sin_iva":      0.0,
                "iva":          0.0,
                "monto_total":  0.0,
            }
        g = grupos[nombre]
        g["cantidad_sum"] += it["cantidad"]
        g["precio_sum"]   += it["precio_unitario"]
        g["precio_count"] += 1
        g["sin_iva"]      += it["sin_iva"]
        g["iva"]          += it["iva"]
        g["monto_total"]  += it["monto_total"]

    result: list[ItemAgrupado] = []
    for nombre in sorted(grupos.keys(), key=str.upper):
        g = grupos[nombre]
        result.append({
            "descripcion":              g["descripcion"],
            "cantidad_total":           g["cantidad_sum"],
            "precio_unitario_promedio": _round2(g["precio_sum"] / g["precio_count"]),
            "sin_iva":                  _round2(g["sin_iva"]),
            "iva":                      _round2(g["iva"]),
            "monto_total":              _round2(g["monto_total"]),
        })
    return result
