"""Servicio para dividir el PDF consolidado O&M por proyecto.

Estructura del PDF Solenium:
  Cada página = una factura electrónica DIAN independiente.
  El nombre del proyecto aparece en dos lugares:
    1. Descripción: "Mantenimiento Preventivo - [NOMBRE] - [Mes]"
    2. Observaciones: "AUTORRETENEDORES ICA MEDELLIN - [NOMBRE] - [Mes]"
  Los nombres del PDF pueden diferir de los de la BD:
    PDF: "Minigranja Solar Cañahuate"  → BD: "MGS 0005 Cañahuate"
    PDF: "Minigranja Solar Gandalf"    → BD: "MGS 0004 Valle de Gandalf"
  Estrategia: extraer la parte distintiva del nombre (quitar prefijo
  "Minigranja Solar" y códigos MGS) y buscarla por substring en los nombres BD.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

# ── Meses ────────────────────────────────────────────────────────────────────
_MESES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
_MESES_PAT = "|".join(_MESES)

# ── Regex extracción nombre de proyecto ──────────────────────────────────────
# Patrón primario: "Mantenimiento Preventivo - NOMBRE - Mes"
_DESC_RE = re.compile(
    rf"Mantenimiento\s+Preventivo\s*-\s*(.+?)\s*-\s*(?:{_MESES_PAT})",
    re.IGNORECASE | re.DOTALL,
)
# Patrón alternativo: "AUTORRETENEDORES ICA MEDELLIN - NOMBRE - Mes"
_OBS_RE = re.compile(
    rf"AUTORRETENEDORES\s+ICA\s+MEDELLIN\s*-\s*(.+?)\s*-\s*(?:{_MESES_PAT})",
    re.IGNORECASE | re.DOTALL,
)

# ── Regex extracción metadata de factura ─────────────────────────────────────
_FACTURA_NO_RE = re.compile(
    r"(?:Factura\s+Electr[oó]nica\s+de\s+Venta\s+No\.?\s*[:.]?\s*|No\.?\s+de\s+factura\s*[:.]?\s*)(SOFV\s*\d+)",
    re.IGNORECASE,
)
_TOTAL_SIN_IMP_RE = re.compile(
    r"Total\s+sin\s+impuestos\s*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_IVA_RE = re.compile(
    r"\bIVA\b[^$\n]*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_TOTAL_PAGAR_RE = re.compile(
    r"Total\s+(?:a\s+pagar|factura|valor)\s*\$?\s*([\d.,]+)",
    re.IGNORECASE,
)
_FECHA_RE = re.compile(
    r"(?:Fecha\s+(?:de\s+)?(?:facturaci[oó]n|factura|emisi[oó]n)\s*[:.]?\s*)(\d{2}[-/]\d{2}[-/]\d{4}|\d{4}[-/]\d{2}[-/]\d{2})",
    re.IGNORECASE,
)
_CUFE_RE = re.compile(
    r"CUFE\s*[:.]?\s*([a-f0-9]{40,})",
    re.IGNORECASE,
)

# ── Prefijos comunes a quitar para obtener nombre distintivo ─────────────────
_PREFIJO_RE = re.compile(
    r"^(?:Mini\s*granja\s+Solar|MGS\s*\d+|SOFV\s*\d+)\s*",
    re.IGNORECASE,
)

_UMBRAL_FUZZY = 0.78


# ── Utilidades ────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    """NFKD + minúsculas + sin diacríticos."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _nombre_distintivo(nombre: str) -> str:
    """Quita prefijos comunes (Minigranja Solar, MGS 0005) para comparación."""
    return _PREFIJO_RE.sub("", nombre).strip()


def _parse_monto(texto: str | None) -> Decimal | None:
    if not texto:
        return None
    limpio = re.sub(r"[^\d,.]", "", texto.strip())
    # Formato colombiano: puntos de miles, coma decimal → quitar puntos, coma→punto
    if "," in limpio and "." in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return Decimal(limpio)
    except InvalidOperation:
        return None


def _safe_filename(nombre: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "-", nombre)


# ── Extracción de una página ──────────────────────────────────────────────────

def extraer_datos_pagina(texto_pagina: str) -> dict:
    """
    Extrae nombre del proyecto y metadata de factura del texto de una página.

    Returns:
        {
          'nombre_proyecto': str | None,
          'estrategia': str | None,
          'numero_factura': str | None,
          'total_sin_impuestos': Decimal | None,
          'iva': Decimal | None,
          'total_pagar': Decimal | None,
          'fecha_facturacion': str | None,   # ISO YYYY-MM-DD o texto original
          'cufe': str | None,
        }
    """
    # Aplanar para regex que cruzan líneas
    texto_flat = re.sub(r"\s+", " ", texto_pagina)

    # Nombre del proyecto
    nombre = None
    estrategia = None
    for patron, etiqueta in ((_DESC_RE, "mantenimiento_preventivo"), (_OBS_RE, "autorretenedores")):
        m = patron.search(texto_flat)
        if m:
            candidato = m.group(1).strip()
            if len(candidato) >= 3:
                nombre = candidato
                estrategia = etiqueta
                break

    # Número de factura
    m_fac = _FACTURA_NO_RE.search(texto_flat)
    numero_factura = m_fac.group(1).replace(" ", "") if m_fac else None

    # Montos
    m_sin = _TOTAL_SIN_IMP_RE.search(texto_flat)
    m_iva = _IVA_RE.search(texto_flat)
    m_tot = _TOTAL_PAGAR_RE.search(texto_flat)

    # Fecha
    m_fecha = _FECHA_RE.search(texto_flat)
    fecha_raw = m_fecha.group(1) if m_fecha else None
    fecha_iso = None
    if fecha_raw:
        partes = re.split(r"[-/]", fecha_raw)
        if len(partes) == 3:
            if len(partes[0]) == 4:                  # YYYY-MM-DD
                fecha_iso = fecha_raw.replace("/", "-")
            else:                                     # DD-MM-YYYY → YYYY-MM-DD
                fecha_iso = f"{partes[2]}-{partes[1]}-{partes[0]}"

    # CUFE
    m_cufe = _CUFE_RE.search(texto_flat)

    return {
        "nombre_proyecto": nombre,
        "estrategia": estrategia,
        "numero_factura": numero_factura,
        "total_sin_impuestos": _parse_monto(m_sin.group(1) if m_sin else None),
        "iva": _parse_monto(m_iva.group(1) if m_iva else None),
        "total_pagar": _parse_monto(m_tot.group(1) if m_tot else None),
        "fecha_facturacion": fecha_iso,
        "cufe": m_cufe.group(1) if m_cufe else None,
    }


# ── Matching ──────────────────────────────────────────────────────────────────

def match_proyecto(nombre_extraido: str, contratos: list[dict]) -> tuple[int | None, float]:
    """
    Devuelve (contrato_id, ratio) del mejor match.

    Estrategia en orden:
    1. Substring exacto del nombre distintivo en el nombre BD normalizado
    2. SequenceMatcher sobre nombre completo normalizado (umbral 0.78)
    """
    if not contratos:
        return None, 0.0

    norm_extraido = _normalizar(nombre_extraido)
    distintivo = _normalizar(_nombre_distintivo(nombre_extraido))

    mejor_ratio = 0.0
    mejor_id = None

    for c in contratos:
        norm_bd = _normalizar(c["nombre_proyecto"])
        distintivo_bd = _normalizar(_nombre_distintivo(c["nombre_proyecto"]))

        # Estrategia 1: substring bidireccional del nombre distintivo
        if distintivo and len(distintivo) >= 4:
            if distintivo in norm_bd or distintivo_bd in norm_extraido:
                return c["contrato_id"], 1.0

        # Estrategia 2: fuzzy sobre nombre completo
        ratio = SequenceMatcher(None, norm_extraido, norm_bd).ratio()
        if ratio > mejor_ratio:
            mejor_ratio = ratio
            mejor_id = c["contrato_id"]

    if mejor_ratio >= _UMBRAL_FUZZY:
        return mejor_id, mejor_ratio
    return None, mejor_ratio


# ── Función principal ─────────────────────────────────────────────────────────

def dividir_pdf(
    ruta_pdf: Path,
    periodo: str,
    contratos: list[dict],
    directorio_salida: Path,
) -> dict:
    """
    Divide el PDF consolidado en PDFs individuales por proyecto.

    Returns:
        {
          'procesados': [{
            'contrato_id', 'nombre', 'archivo', 'ruta_local',
            'numero_factura', 'total_sin_impuestos', 'iva', 'total_pagar',
            'fecha_facturacion', 'cufe',
          }],
          'sin_match': [{
            'pagina', 'nombre_extraido', 'estrategia', 'razon', 'muestra_texto',
            'numero_factura',
          }],
        }
    """
    directorio_salida.mkdir(parents=True, exist_ok=True)
    sin_match: list[dict] = []
    # paginas_por_contrato: contrato_id → (lista_indices, datos_ultima_factura)
    paginas_por_contrato: dict[int, tuple[list[int], dict]] = {}

    reader = PdfReader(str(ruta_pdf))
    with pdfplumber.open(ruta_pdf) as pdf:
        for i, pagina in enumerate(pdf.pages):
            texto = pagina.extract_text() or ""
            datos = extraer_datos_pagina(texto)
            nombre = datos["nombre_proyecto"]

            if not nombre:
                sin_match.append({
                    "pagina": i + 1,
                    "nombre_extraido": None,
                    "estrategia": None,
                    "razon": "no_se_extrajo_nombre",
                    "muestra_texto": texto[:300].strip(),
                    "numero_factura": datos.get("numero_factura"),
                })
                continue

            contrato_id, ratio = match_proyecto(nombre, contratos)
            if contrato_id is None:
                sin_match.append({
                    "pagina": i + 1,
                    "nombre_extraido": nombre,
                    "estrategia": datos["estrategia"],
                    "razon": f"sin_match_fuzzy (mejor ratio: {ratio:.2f})",
                    "muestra_texto": nombre,
                    "numero_factura": datos.get("numero_factura"),
                })
                continue

            if contrato_id not in paginas_por_contrato:
                paginas_por_contrato[contrato_id] = ([], datos)
            paginas_por_contrato[contrato_id][0].append(i)

    # Escribir un PDF por contrato con todas sus páginas
    procesados: list[dict] = []
    for contrato_id, (indices, datos) in paginas_por_contrato.items():
        contrato = next(c for c in contratos if c["contrato_id"] == contrato_id)
        safe_nombre = _safe_filename(contrato["nombre_proyecto"])
        nombre_archivo = f"SOFV_{safe_nombre}_{periodo}_mantenimiento.pdf"
        ruta_salida = directorio_salida / nombre_archivo

        writer = PdfWriter()
        for idx in indices:
            writer.add_page(reader.pages[idx])
        with open(ruta_salida, "wb") as f:
            writer.write(f)

        procesados.append({
            "contrato_id": contrato_id,
            "nombre": contrato["nombre_proyecto"],
            "archivo": nombre_archivo,
            "ruta_local": str(ruta_salida),
            "numero_factura": datos.get("numero_factura"),
            "total_sin_impuestos": datos.get("total_sin_impuestos"),
            "iva": datos.get("iva"),
            "total_pagar": datos.get("total_pagar"),
            "fecha_facturacion": datos.get("fecha_facturacion"),
            "cufe": datos.get("cufe"),
        })

    return {"procesados": procesados, "sin_match": sin_match}
