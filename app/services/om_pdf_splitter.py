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

# Líneas de encabezado/footer que deben ignorarse para el matching
_LINEAS_RUIDO = re.compile(
    r"SOLENIUM|NIT\s*:|Resoluci[oó]n\s+DIAN|facturaci[oó]n\s+electr[oó]nica"
    r"|Tel[eé]fono\s*:|solenium\.com|@\w+\.\w+|p[aá]gina\s+\d",
    re.IGNORECASE,
)

# Estrategias de extracción, en orden de preferencia
# Patrones aplicados sobre texto con saltos de línea preservados (capturan hasta \n)
_ESTRATEGIAS_MULTILINEA: list[tuple[str, re.Pattern]] = [
    # 1. Etiqueta explícita "Nombre del Proyecto: ..."
    ("etiqueta_nombre", re.compile(
        r"Nombre\s+del\s+Proyecto\s*[:\-]\s*(.+?)(?:\r?\n|$)",
        re.IGNORECASE,
    )),
    # 2. "Proyecto: ..." (variante corta)
    ("etiqueta_proyecto", re.compile(
        r"(?<!\w)Proyecto\s*[:\-]\s*(.+?)(?:\r?\n|$)",
        re.IGNORECASE,
    )),
]

# Patrones aplicados sobre texto aplanado (sin saltos de línea)
_ESTRATEGIAS_FLAT: list[tuple[str, re.Pattern]] = [
    # 3. Descripción clásica Solenium: "Mantenimiento Preventivo - Nombre - Mes"
    ("descripcion_mantenimiento", re.compile(
        rf"Mantenimiento\s+\w+\s*-\s*(.+?)\s*-\s*(?:{_MESES_PAT})",
        re.IGNORECASE | re.DOTALL,
    )),
    # 4. "Mini granja Solar ..." o "Minigranja Solar ..."
    ("minigranja", re.compile(
        r"Mini\s*granja\s+Solar\s+([\w][\w\s]+?)(?:\s*[-,\d]|$)",
        re.IGNORECASE,
    )),
    # 5. "SOFV... Nombre" — código de factura seguido del nombre
    ("sofv", re.compile(
        r"SOFV\s*\d+\s+([\w][\w\s]+?)(?:\s*[-,]|$)",
        re.IGNORECASE,
    )),
]

_UMBRAL = 0.80  # reducido de 0.85 para tolerar variaciones de formato


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _filtrar_ruido(texto: str) -> str:
    """Elimina líneas de encabezado/footer para quedarse solo con el cuerpo."""
    lineas = texto.splitlines()
    return "\n".join(l for l in lineas if not _LINEAS_RUIDO.search(l))


def extraer_nombre_pagina(texto_pagina: str) -> tuple[str | None, str | None]:
    """
    Extrae el nombre del proyecto del texto de una página de factura Solenium.

    Retorna: (nombre_extraido, estrategia_usada)
    Si no encuentra nada: (None, None)
    """
    texto_limpio = _filtrar_ruido(texto_pagina)

    # Primero: patrones sobre texto con saltos de línea (etiquetas "Nombre del Proyecto:")
    for estrategia, patron in _ESTRATEGIAS_MULTILINEA:
        m = patron.search(texto_limpio)
        if m:
            nombre = m.group(1).strip()
            if len(nombre) >= 4 and not re.fullmatch(r"[\d\W]+", nombre):
                return nombre, estrategia

    # Segundo: patrones sobre texto aplanado (descripciones de línea larga)
    texto_flat = re.sub(r"\s+", " ", texto_limpio)
    for estrategia, patron in _ESTRATEGIAS_FLAT:
        m = patron.search(texto_flat)
        if m:
            nombre = m.group(1).strip()
            if len(nombre) >= 4 and not re.fullmatch(r"[\d\W]+", nombre):
                return nombre, estrategia

    return None, None


def match_proyecto(nombre_extraido: str, contratos: list[dict]) -> tuple[int | None, float]:
    """
    Devuelve (contrato_id, ratio) del contrato con mayor similitud.
    Retorna (None, ratio) si ninguno supera el umbral.
    """
    if not contratos:
        return None, 0.0
    norm = _normalizar(nombre_extraido)
    mejor_ratio = 0.0
    mejor_id = None
    for c in contratos:
        ratio = SequenceMatcher(None, norm, _normalizar(c["nombre_proyecto"])).ratio()
        if ratio > mejor_ratio:
            mejor_ratio = ratio
            mejor_id = c["contrato_id"]
    if mejor_ratio >= _UMBRAL:
        return mejor_id, mejor_ratio
    return None, mejor_ratio


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

    Returns:
        {
          'procesados': [{'contrato_id', 'nombre', 'archivo', 'ruta_local'}],
          'sin_match':  [{'pagina', 'texto_identificado', 'estrategia', 'razon'}],
        }
    """
    directorio_salida.mkdir(parents=True, exist_ok=True)
    sin_match: list[dict] = []
    paginas_por_contrato: dict[int, list[int]] = {}

    reader = PdfReader(str(ruta_pdf))
    with pdfplumber.open(ruta_pdf) as pdf:
        for i, pagina in enumerate(pdf.pages):
            texto = pagina.extract_text() or ""
            nombre, estrategia = extraer_nombre_pagina(texto)

            if not nombre:
                sin_match.append({
                    "pagina": i + 1,
                    "texto_identificado": None,
                    "estrategia": None,
                    "razon": "no_se_extrajo_nombre",
                    "muestra_texto": texto[:300].strip(),
                })
                continue

            contrato_id, ratio = match_proyecto(nombre, contratos)
            if contrato_id is None:
                sin_match.append({
                    "pagina": i + 1,
                    "texto_identificado": nombre,
                    "estrategia": estrategia,
                    "razon": f"sin_match_fuzzy (mejor ratio: {ratio:.2f})",
                    "muestra_texto": nombre,
                })
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
