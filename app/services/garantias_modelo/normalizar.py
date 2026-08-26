"""Normalización de texto, fechas y versiones de liquidación.

Puro: sin estado, sin dependencias de FastAPI ni SQLAlchemy.
"""
from __future__ import annotations

import datetime
import re
import unicodedata

# Los tres formatos conviven en el corpus real. Ver el spec, §6.1.
_MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

_RE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_RE_DDMMM = re.compile(r"(\d{1,2})([A-Z]{3,4})-?(20\d{2})")
_RE_VERSION = re.compile(r"\.(tx[0-9a-z])$", re.IGNORECASE)

# Orden de liquidación. Sucesivas versiones corrigen a las anteriores.
_ORDEN = {"tx1": 1, "tx2": 2, "tx3": 3, "txr": 4, "txf": 5, "txn": 6}
_ORDEN_DESCONOCIDA = 99


def normalizar_concepto(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin espacios repetidos.

    Absorbe la doble codificación de 6 de los CSV de CGM, donde las tildes llegan
    como `ï¿½` y romperían un match literal sin lanzar error.
    """
    if texto is None:
        return ""
    # El orden importa: `ï¿½` son TRES caracteres y NFKD expande el `½` a `1⁄2`,
    # con lo que el marcador deja de existir y queda basura. Limpiar primero.
    s = str(texto).replace("ï¿½", "").replace("�", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def coincide_concepto(a: str | None, b: str | None) -> bool:
    """¿Son el mismo concepto, tolerando doble codificación?

    No alcanza con comparar por igualdad: el mojibake **destruye** el carácter
    acentuado, así que `Generaciï¿½n Kw` normaliza a `generacin kw` y nunca va a ser
    igual a `generacion kw`. Pero le faltan caracteres, no le sobran — la forma
    corrupta es una subsecuencia de la limpia. Eso sí es verificable, y no confunde
    conceptos genuinamente distintos.
    """
    x, y = normalizar_concepto(a), normalizar_concepto(b)
    if x == y:
        return True
    corta, larga = (x, y) if len(x) <= len(y) else (y, x)
    if not corta or len(larga) - len(corta) > 3:
        return False
    it = iter(larga)
    return all(c in it for c in corta)


def fecha_de_nombre(nombre: str) -> datetime.date | None:
    """Extrae la fecha de un nombre de archivo. None si no hay ninguna.

    Cubre los dos formatos que conviven (`02ENE-2026` e ISO) y el `SEPT` de cuatro
    letras. ISO primero: es inequívoco.
    """
    m = _RE_ISO.search(nombre)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _RE_DDMMM.search(nombre.upper())
    if m and m.group(2) in _MESES:
        try:
            return datetime.date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def version_de_nombre(nombre: str) -> str | None:
    """`BalCttos0101.tx2` -> `tx2`. None si la extensión no es de liquidación."""
    m = _RE_VERSION.search(nombre)
    return m.group(1).lower() if m else None


def orden_version(version: str | None) -> int:
    """Ordinal de la versión. Las desconocidas van al final, nunca al principio:
    ante la duda, no deben ganarle a una versión conocida.

    Este plan no la consume — la usa el plan 3 para elegir la versión vigente a una
    fecha. Va acá porque el orden de liquidación es dominio, no del motor.
    """
    return _ORDEN.get((version or "").lower(), _ORDEN_DESCONOCIDA)
