"""Ingesta del Precio de Bolsa Nacional desde archivos de XM.

XM publica el precio de bolsa en un formato "ancho": una fila por día y una
columna por hora (0..23, o "Hora 00".."Hora 23"), con el precio en COP/kWh.
Este utilitario aplana ese formato a una lista de dicts
`{"fecha_hora": datetime, "precio_cop_mwh": Decimal}` lista para
`bulk_upsert_precio_bolsa` (ver app/services/riesgos_bolsa.py).

Se apoya en pandas (ya usado por app/services/xm/unificador.py) y en el mismo
separador `;` y tolerancia de encoding que el resto del pipeline XM.
"""
import io
import logging
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import pandas as pd

logger = logging.getLogger(__name__)

# COP/kWh → COP/MWh
KWH_A_MWH = Decimal(1000)

_COLUMNAS_FECHA = ("fecha", "date", "fechahora", "fecha_hora", "dia")


class XMPrecioBolsaParseError(ValueError):
    """El archivo de XM no pudo interpretarse como precio de bolsa."""


def _leer_dataframe(file_path: str) -> pd.DataFrame:
    """Lee CSV (sep=';') o Excel según la extensión, tolerando encoding."""
    lower = file_path.lower()
    try:
        if lower.endswith((".xlsx", ".xls")):
            return pd.read_excel(file_path)
        try:
            return pd.read_csv(file_path, sep=";", encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(file_path, sep=";", encoding="latin1")
    except FileNotFoundError:
        raise
    except Exception as e:  # pragma: no cover - defensivo
        raise XMPrecioBolsaParseError(f"No se pudo leer el archivo '{file_path}': {e}") from e


def _detectar_columna_fecha(df: pd.DataFrame) -> str:
    for col in df.columns:
        if str(col).strip().lower() in _COLUMNAS_FECHA:
            return col
    # Fallback: primera columna.
    if len(df.columns):
        return df.columns[0]
    raise XMPrecioBolsaParseError("El archivo no tiene columnas.")


def _hora_de_columna(col) -> int | None:
    """Extrae la hora (0..23) del nombre de una columna.

    Acepta '0'..'23', 'Hora 0', 'HORA 01', 'H1', etc. Devuelve None si la
    columna no representa una hora válida.
    """
    texto = str(col).strip()
    m = re.search(r"(\d{1,2})", texto)
    if not m:
        return None
    hora = int(m.group(1))
    return hora if 0 <= hora <= 23 else None


def _a_decimal(valor) -> Decimal | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
        if not valor:
            return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def parse_xm_precio_bolsa_df(
    df: pd.DataFrame,
    *,
    convertir_kwh_a_mwh: bool = True,
) -> list[dict]:
    """Aplana un DataFrame ancho de precio de bolsa a filas horarias.

    Args:
        df: DataFrame con una columna de fecha y columnas horarias 0..23.
        convertir_kwh_a_mwh: si True (XM publica en COP/kWh) multiplica x1000
            para almacenar en COP/MWh; si el archivo ya viene en COP/MWh usar
            False.

    Returns:
        Lista de dicts `{"fecha_hora": datetime, "precio_cop_mwh": Decimal}`,
        ordenada por fecha_hora, sin horas con precio nulo/ilegible.
    """
    if df is None or df.empty:
        return []

    col_fecha = _detectar_columna_fecha(df)
    columnas_hora: list[tuple[str, int]] = []
    for col in df.columns:
        if col == col_fecha:
            continue
        hora = _hora_de_columna(col)
        if hora is not None:
            columnas_hora.append((col, hora))

    if not columnas_hora:
        raise XMPrecioBolsaParseError(
            "No se encontraron columnas horarias (0..23) en el archivo de XM."
        )

    filas: list[dict] = []
    for _, row in df.iterrows():
        valor_fecha = row[col_fecha]
        try:
            dia = pd.to_datetime(valor_fecha).date()
        except Exception:
            logger.warning("Fecha ilegible, fila omitida: %r", valor_fecha)
            continue
        if not isinstance(dia, date):
            continue

        for col, hora in columnas_hora:
            precio = _a_decimal(row[col])
            if precio is None:
                continue
            if convertir_kwh_a_mwh:
                precio = precio * KWH_A_MWH
            filas.append(
                {
                    "fecha_hora": datetime(dia.year, dia.month, dia.day, hora),
                    # Cuantiza a 2 decimales para respetar NUMERIC(10,2).
                    "precio_cop_mwh": precio.quantize(Decimal("0.01")),
                }
            )

    filas.sort(key=lambda f: f["fecha_hora"])
    return filas


def parse_xm_precio_bolsa(
    file_path: str,
    *,
    convertir_kwh_a_mwh: bool = True,
) -> list[dict]:
    """Lee un archivo de XM y devuelve las filas horarias de precio de bolsa.

    Raises:
        FileNotFoundError: si el archivo no existe.
        XMPrecioBolsaParseError: si el archivo no tiene el formato esperado.
    """
    df = _leer_dataframe(file_path)
    return parse_xm_precio_bolsa_df(df, convertir_kwh_a_mwh=convertir_kwh_a_mwh)


def parse_xm_precio_bolsa_bytes(
    contenido: bytes,
    *,
    convertir_kwh_a_mwh: bool = True,
) -> list[dict]:
    """Igual que parse_xm_precio_bolsa pero desde bytes en memoria (CSV)."""
    try:
        df = pd.read_csv(io.BytesIO(contenido), sep=";", encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(contenido), sep=";", encoding="latin1")
    except Exception as e:
        raise XMPrecioBolsaParseError(f"No se pudo interpretar el contenido: {e}") from e
    return parse_xm_precio_bolsa_df(df, convertir_kwh_a_mwh=convertir_kwh_a_mwh)
