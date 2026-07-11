"""Servicio de ingesta de archivos Excel de liquidación XM.

Parsea `listado_recursos.xlsx` y `generacion_distribuida.xlsx`, mapea sus
columnas al modelo `LiquidacionXMDatoIngesta`, calcula un hash por fila para
deduplicar y persiste en bloque vía la capa CRUD.

El parseo es tolerante a variaciones de encabezado (mayúsculas, acentos,
espacios) porque los archivos que publica XM no siempre traen los nombres de
columna idénticos entre períodos.
"""
import hashlib
import logging
import os
import re
import unicodedata
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.crud import crud_liquidacion_xm
from app.schemas.liquidacion_xm import LiquidacionXMDatoCreate

logger = logging.getLogger(__name__)

# Tipos de archivo soportados.
FILE_TYPE_LISTADO = "listado_recursos"
FILE_TYPE_GENERACION = "generacion_distribuida"
FILE_TYPES = (FILE_TYPE_LISTADO, FILE_TYPE_GENERACION)

# Candidatos de encabezado por campo (normalizados: minúsculas, sin acentos,
# separados por "_"). El primero que aparezca en el archivo gana.
_COLUMNAS_CANDIDATAS: dict[str, list[str]] = {
    "codigo_recurso": [
        "codigo_recurso", "codigo_del_recurso", "codigo_sic", "codigo", "recurso",
    ],
    "fecha": ["fecha", "fecha_operacion", "fecha_de_operacion", "dia"],
    "agente": ["agente", "agente_representante", "representante", "comercializador"],
    "tipo_recurso": [
        "tipo_recurso", "tipo_de_recurso", "tipo", "tecnologia", "tipo_tecnologia",
    ],
    "capacidad_efectiva_neta_mw": [
        "capacidad_efectiva_neta_mw", "capacidad_efectiva_neta", "capacidad_efectiva",
        "capacidad", "cen_mw", "cen",
    ],
    "generacion_kwh": [
        "generacion_kwh", "generacion", "energia_kwh", "energia", "generacion_real_kwh",
    ],
    "precio_liquidacion_cop_kwh": [
        "precio_liquidacion_cop_kwh", "precio_liquidacion", "precio_cop_kwh",
        "precio", "precio_bolsa", "precio_promedio",
    ],
    "valor_liquidacion_cop": [
        "valor_liquidacion_cop", "valor_liquidacion", "valor_cop", "valor",
    ],
}

# Campos numéricos (para el coercing de tipos).
_CAMPOS_NUMERICOS = (
    "capacidad_efectiva_neta_mw",
    "generacion_kwh",
    "precio_liquidacion_cop_kwh",
    "valor_liquidacion_cop",
)


def normalizar_header(nombre: object) -> str:
    """Normaliza un encabezado: sin acentos, minúsculas, separadores '_'."""
    s = "" if nombre is None else str(nombre)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.strip().lower()
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def to_float(valor: object) -> Optional[float]:
    """Convierte a float tolerando formatos es-CO ('1.234,56') y en-US ('1234.56')."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        f = float(valor)
        return None if pd.isna(f) else f
    s = str(valor).strip()
    if not s or s.lower() in ("nan", "none", "-", "n/a", "na"):
        return None
    s = s.replace(" ", "").replace("$", "")
    if "," in s and "." in s:
        # es-CO: el punto es separador de miles, la coma es decimal.
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def to_date(valor: object) -> Optional[date]:
    """Parsea una fecha; devuelve None si no se puede interpretar."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, date):
        return valor
    # Las fechas ISO (YYYY-MM-DD) son inequívocas; para formatos con "/" o "."
    # asumimos día primero (convención es-CO). dayfirst sobre una fecha ISO haría
    # que pandas la malinterprete (2026-07-11 -> 7 de noviembre), de ahí la distinción.
    s = str(valor).strip()
    es_iso = bool(re.match(r"^\d{4}-\d{1,2}-\d{1,2}", s))
    ts = pd.to_datetime(valor, dayfirst=not es_iso, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def compute_row_hash(
    *,
    fuente_archivo: str,
    codigo_recurso: str,
    fecha: date,
    generacion_kwh: Optional[float],
    precio_liquidacion_cop_kwh: Optional[float],
    valor_liquidacion_cop: Optional[float],
    agente: Optional[str] = None,
    tipo_recurso: Optional[str] = None,
    capacidad_efectiva_neta_mw: Optional[float] = None,
) -> str:
    """Hash SHA-256 determinista de una fila, para deduplicar en la ingesta.

    El mismo contenido lógico produce siempre el mismo hash, independientemente
    del orden en que se procesen los archivos.
    """
    def _n(v: Optional[float]) -> str:
        return "" if v is None else format(float(v), ".4f")

    partes = [
        fuente_archivo or "",
        (codigo_recurso or "").strip().upper(),
        fecha.isoformat() if fecha else "",
        (agente or "").strip().upper(),
        (tipo_recurso or "").strip().upper(),
        _n(capacidad_efectiva_neta_mw),
        _n(generacion_kwh),
        _n(precio_liquidacion_cop_kwh),
        _n(valor_liquidacion_cop),
    ]
    base = "|".join(partes)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _mapear_columnas(columnas: list[str]) -> dict[str, str]:
    """Mapea nombre_normalizado -> nombre_original para cada campo del modelo."""
    norm_a_original = {normalizar_header(c): c for c in columnas}
    mapeo: dict[str, str] = {}
    for campo, candidatos in _COLUMNAS_CANDIDATAS.items():
        for cand in candidatos:
            if cand in norm_a_original:
                mapeo[campo] = norm_a_original[cand]
                break
    return mapeo


def parse_dataframe(
    df: pd.DataFrame,
    file_type: str,
    fuente_archivo: str,
    fecha_default: Optional[date] = None,
) -> tuple[list[LiquidacionXMDatoCreate], list[str]]:
    """Convierte un DataFrame en objetos `LiquidacionXMDatoCreate`.

    Devuelve (datos, errores). Errores por fila no abortan el proceso; se
    acumulan y se reportan. Falta de la columna `codigo_recurso` sí es fatal.
    """
    if file_type not in FILE_TYPES:
        raise ValueError(f"file_type inválido: {file_type!r}. Use uno de {FILE_TYPES}.")

    mapeo = _mapear_columnas(list(df.columns))
    if "codigo_recurso" not in mapeo:
        raise ValueError(
            "El archivo no contiene una columna de código de recurso reconocible "
            f"(columnas: {list(df.columns)})."
        )

    datos: list[LiquidacionXMDatoCreate] = []
    errores: list[str] = []

    for idx, row in df.iterrows():
        try:
            codigo = row[mapeo["codigo_recurso"]]
            codigo = None if codigo is None or pd.isna(codigo) else str(codigo).strip()
            if not codigo:
                continue  # fila vacía / de totales

            fecha = to_date(row[mapeo["fecha"]]) if "fecha" in mapeo else None
            if fecha is None:
                fecha = fecha_default
            if fecha is None:
                errores.append(f"fila {idx}: sin fecha y sin fecha_default")
                continue

            campos: dict = {"codigo_recurso": codigo, "fecha": fecha}
            for campo in ("agente", "tipo_recurso"):
                if campo in mapeo:
                    val = row[mapeo[campo]]
                    campos[campo] = None if val is None or pd.isna(val) else str(val).strip()
            for campo in _CAMPOS_NUMERICOS:
                if campo in mapeo:
                    campos[campo] = to_float(row[mapeo[campo]])

            campos["fuente_archivo"] = fuente_archivo
            campos["hash_fila"] = compute_row_hash(
                fuente_archivo=fuente_archivo,
                codigo_recurso=codigo,
                fecha=fecha,
                generacion_kwh=campos.get("generacion_kwh"),
                precio_liquidacion_cop_kwh=campos.get("precio_liquidacion_cop_kwh"),
                valor_liquidacion_cop=campos.get("valor_liquidacion_cop"),
                agente=campos.get("agente"),
                tipo_recurso=campos.get("tipo_recurso"),
                capacidad_efectiva_neta_mw=campos.get("capacidad_efectiva_neta_mw"),
            )
            datos.append(LiquidacionXMDatoCreate(**campos))
        except Exception as e:  # noqa: BLE001 — errores por fila no deben abortar todo
            errores.append(f"fila {idx}: {e}")

    return datos, errores


def _detectar_file_type(nombre: str) -> Optional[str]:
    """Infiere el file_type a partir del nombre del archivo."""
    norm = normalizar_header(nombre)
    if "listado" in norm and "recurso" in norm:
        return FILE_TYPE_LISTADO
    if "generacion" in norm and ("distribuida" in norm or "gd" in norm):
        return FILE_TYPE_GENERACION
    return None


def process_xm_file(
    db: Session,
    file_path: str,
    file_type: Optional[str] = None,
    *,
    fuente_archivo: Optional[str] = None,
    fecha_default: Optional[date] = None,
) -> dict:
    """Procesa un archivo Excel XM: lee, valida, deduplica y persiste.

    Devuelve un resumen (ver `schemas.liquidacion_xm.IngestionResumen`).
    Lanza ValueError si el archivo o el tipo no son válidos.
    """
    nombre = os.path.basename(file_path)
    if file_type is None:
        file_type = _detectar_file_type(nombre)
    if file_type not in FILE_TYPES:
        raise ValueError(
            f"No se pudo determinar el tipo de archivo XM para {nombre!r}. "
            f"Especifique file_type: {FILE_TYPES}."
        )
    if fuente_archivo is None:
        fuente_archivo = nombre

    try:
        df = pd.read_excel(file_path, engine="openpyxl", dtype=object)
    except Exception as e:
        raise ValueError(f"No se pudo leer el archivo Excel {nombre!r}: {e}") from e

    datos, errores = parse_dataframe(df, file_type, fuente_archivo, fecha_default)
    nuevas = crud_liquidacion_xm.create_multiple(db, datos)

    resumen = {
        "fuente_archivo": fuente_archivo,
        "file_type": file_type,
        "filas_leidas": int(len(df)),
        "filas_nuevas": nuevas,
        "filas_duplicadas": len(datos) - nuevas,
        "errores": errores,
    }
    logger.info(
        "[xm_ingestion] %s (%s): leidas=%s nuevas=%s duplicadas=%s errores=%s",
        fuente_archivo, file_type, resumen["filas_leidas"], resumen["filas_nuevas"],
        resumen["filas_duplicadas"], len(errores),
    )
    return resumen
