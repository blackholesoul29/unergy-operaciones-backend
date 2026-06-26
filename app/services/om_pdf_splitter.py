"""Servicio para dividir el PDF consolidado O&M por proyecto."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

_MESES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
_MESES_PAT = "|".join(_MESES)
_DESC_RE = re.compile(
    rf"Mantenimiento\s+\w+\s*-\s*(.+?)\s*-\s*(?:{_MESES_PAT})",
    re.IGNORECASE | re.DOTALL,
)
_UMBRAL = 0.85


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def extraer_nombre_pagina(texto_pagina: str) -> str | None:
    """Extrae el nombre del proyecto del texto de una página de factura Solenium."""
    texto = re.sub(r"\s+", " ", texto_pagina)
    m = _DESC_RE.search(texto)
    if not m:
        return None
    return m.group(1).strip()


def match_proyecto(nombre_extraido: str, contratos: list[dict]) -> int | None:
    """
    Devuelve el contrato_id del contrato con mayor similitud al nombre extraído.
    Retorna None si ninguno supera el umbral de 0.85.
    """
    if not contratos:
        return None
    norm = _normalizar(nombre_extraido)
    mejor_ratio = 0.0
    mejor_id = None
    for c in contratos:
        ratio = SequenceMatcher(None, norm, _normalizar(c["nombre_proyecto"])).ratio()
        if ratio > mejor_ratio:
            mejor_ratio = ratio
            mejor_id = c["contrato_id"]
    return mejor_id if mejor_ratio >= _UMBRAL else None


def _safe_filename(nombre: str) -> str:
    return nombre.replace("/", "-").replace("\\", "-")


def dividir_pdf(
    ruta_pdf: Path,
    periodo: str,
    contratos: list[dict],
    directorio_salida: Path,
) -> dict:
    """
    Divide el PDF consolidado en PDFs individuales por proyecto.
    Si un proyecto tiene varias páginas, se combinan en un solo PDF.

    Args:
        ruta_pdf: Path al PDF consolidado ya guardado.
        periodo: Período en formato YYYY-MM.
        contratos: Lista de dicts con keys 'contrato_id' y 'nombre_proyecto'.
        directorio_salida: Directorio donde guardar los PDFs individuales.

    Returns:
        {'procesados': [...], 'sin_match': [...]}
    """
    directorio_salida.mkdir(parents=True, exist_ok=True)
    sin_match: list[dict] = []
    # Acumular índices de página por contrato_id
    paginas_por_contrato: dict[int, list[int]] = {}

    reader = PdfReader(str(ruta_pdf))
    with pdfplumber.open(ruta_pdf) as pdf:
        for i, pagina in enumerate(pdf.pages):
            texto = pagina.extract_text() or ""
            nombre = extraer_nombre_pagina(texto)
            if not nombre:
                sin_match.append({"pagina": i + 1, "texto_extraido": texto[:200]})
                continue

            contrato_id = match_proyecto(nombre, contratos)
            if contrato_id is None:
                sin_match.append({"pagina": i + 1, "texto_extraido": nombre})
                continue

            paginas_por_contrato.setdefault(contrato_id, []).append(i)

    # Escribir un PDF por contrato con todas sus páginas
    procesados: list[dict] = []
    for contrato_id, indices in paginas_por_contrato.items():
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
        })

    return {"procesados": procesados, "sin_match": sin_match}
