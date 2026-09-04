"""Lectura de hilos de correo del CRM comercial.

Todo aqui es funcion pura sobre strings —ni disco ni red— para que los tests
usen fragmentos reales de los correos. Quien abre los .eml es
scripts/parsear_correos_ofertas.py.
"""
import re
from datetime import date

DOMINIO_PROPIO = "unergy.io"

_MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    "jan": 1, "apr": 4, "aug": 8, "dec": 12,
}

# Marcador de mensaje citado de Gmail en espanol. En el text/plain viene
# PARTIDO en varias lineas y el correo suele traer delante los '>' del citado:
#     El lun, 22 jun 2026 a la(s) 11:23 a.m., Alejandro Sepulveda (
#     >>> alejandros@unergy.io) escribio:
# Por eso el patron es DOTALL con un salto acotado hasta "escribio:".
_RE_CITA = re.compile(
    r"El\s+\w{3,10},?\s+(\d{1,2})\s+(?:de\s+)?([A-Za-zÀ-ſ]{3,12})\.?\s+(?:de\s+)?(\d{4})"
    r".{0,200}?escribi[oó]:",
    re.S | re.I,
)
_RE_CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_CODIGO = re.compile(r"No\.?\s*(\d{1,4})\s*-\s*(\d{1,2})\s*-\s*(\d{4})")


def mes_numero(nombre: str) -> int | None:
    """'sept' -> 9. Acepta abreviaturas de 3 o 4 letras y nombres largos."""
    return _MESES.get(nombre.lower().strip(".")[:3])


def mensajes_citados(cuerpo: str) -> list[tuple[date, str]]:
    """(fecha, correo) de cada mensaje citado del hilo, en el orden en que aparecen."""
    # Gmail mete espacios duros (U+00A0) y finos (U+202F) alrededor de la hora;
    # sin normalizarlos el patron no cierra. Van como escape a proposito:
    # un caracter invisible en el codigo fuente es una trampa para el que edite.
    cuerpo = (cuerpo or "").replace(chr(0xA0), " ").replace(chr(0x202F), " ")
    out: list[tuple[date, str]] = []
    for m in _RE_CITA.finditer(cuerpo):
        mes = mes_numero(m.group(2))
        if not mes:
            continue
        correo = _RE_CORREO.search(m.group(0))
        try:
            f = date(int(m.group(3)), mes, int(m.group(1)))
        except ValueError:
            continue
        out.append((f, correo.group(0).lower() if correo else ""))
    return out


def hilo_completo(cuerpo: str, fecha_top: date, correo_top: str) -> list[tuple[date, str]]:
    """Todos los mensajes del hilo (el de arriba + los citados), de viejo a nuevo."""
    msgs = [(fecha_top, (correo_top or "").lower())] + mensajes_citados(cuerpo)
    return sorted(msgs, key=lambda m: m[0])


def _ultima_respuesta(mensajes, dominio: str) -> date | None:
    ajenos = [f for f, c in mensajes if c and not c.endswith("@" + dominio)]
    return max(ajenos) if ajenos else None


def datos_envio(mensajes, mes_codigo: int, anio_codigo: int,
                dominio: str = DOMINIO_PROPIO) -> dict:
    """Datos de envio de UNA oferta dentro del hilo.

    Un hilo puede cubrir varias ofertas (Monterrey: servicios en sep-2025,
    energia en mar-2026). La oferta se fecha con NUESTRO mensaje cuyo mes y anio
    coinciden con los del codigo; si ninguno coincide, con el mas antiguo
    nuestro. Los seguimientos se cuentan desde esa fecha en adelante: una oferta
    de marzo no carga con los toques anteriores a su existencia.
    """
    nuestros = sorted(f for f, c in mensajes if c.endswith("@" + dominio))
    ultima = _ultima_respuesta(mensajes, dominio)
    if not nuestros:
        return {"fecha_oferta": None, "seguimientos": 0, "fecha_ultima_respuesta": ultima}
    coincide = [f for f in nuestros if f.month == mes_codigo and f.year == anio_codigo]
    fecha = coincide[0] if coincide else nuestros[0]
    return {
        "fecha_oferta": fecha,
        "seguimientos": sum(1 for f in nuestros if f >= fecha),
        "fecha_ultima_respuesta": ultima,
    }


def codigo_partes(texto: str) -> tuple[int, int, int] | None:
    """(consecutivo, mes, anio) del codigo embebido en un nombre de archivo o en
    un numero de oferta. Es la clave de union con la base: ignora el prefijo,
    que en el seed es 'OF.' y en produccion 'OP.'."""
    m = _RE_CODIGO.search(texto or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
