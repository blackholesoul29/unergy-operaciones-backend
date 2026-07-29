"""Validación de periodo (YYYY-MM estricto) y de año, compartida por los
endpoints de costos. Puro: sin DB ni FastAPI."""
import re

_PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

ANIO_MIN = 2000
ANIO_MAX = 2100


def periodo_valido(periodo) -> bool:
    """True si `periodo` es un string estricto YYYY-MM (mes 01-12, con cero a la
    izquierda). Rechaza "2026-6" para que no cree duplicados frente a "2026-06"."""
    return isinstance(periodo, str) and bool(_PERIODO_RE.match(periodo))


def anio_valido(año) -> bool:
    """True si `año` es un entero dentro de [ANIO_MIN, ANIO_MAX]."""
    return isinstance(año, int) and not isinstance(año, bool) and ANIO_MIN <= año <= ANIO_MAX
