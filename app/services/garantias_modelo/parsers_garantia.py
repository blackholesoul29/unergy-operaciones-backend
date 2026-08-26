"""Excel de garantía de XM → targets por componente y ventanas por período.

Dos formatos conviven:

- **Nuevo** (oficial desde 2026-09-04, Res CREG 101 097): hojas `DEPOSITO`,
  `PERIODOS A GARANTIZAR`, `PERIODO BASE`. Una sola tabla, cabecera en la fila 1, y la
  ventana en columnas `Fecha Inicial` / `Fecha Final`.
- **Tradicional**: una hoja por período (`AJUSTE TX2 …`, `AJUSTE PROY …`), con la
  ventana embebida en el NOMBRE de la hoja y 2 a 10 filas de metadatos antes de la
  cabecera.

La detección va por las hojas, no por el nombre del archivo: un archivo renombrado no
debe cambiar cómo se parsea.
"""
from __future__ import annotations

import datetime
import re

from app.services.garantias_modelo.normalizar import normalizar_concepto

FORMATO_NUEVO = "nuevo"
FORMATO_TRADICIONAL = "tradicional"

_MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}
_RE_VENTANA = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Z]{3,4})")
_RE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def detectar_formato(hojas: list[str]) -> str | None:
    """`None` si no reconoce ninguno — fallar cerrado, no adivinar."""
    normal = {normalizar_concepto(h) for h in hojas}
    if "periodos a garantizar" in normal:
        return FORMATO_NUEVO
    if any(n.startswith("ajuste") for n in normal):
        return FORMATO_TRADICIONAL
    return None


def _fecha(valor) -> datetime.date | None:
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    m = _RE_ISO.match(str(valor or ""))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def filas_periodos(filas: list[tuple], agente: str) -> list[dict]:
    """Formato NUEVO: una fila por período del agente, desde `PERIODOS A GARANTIZAR`.

    `filas` son las de openpyxl con `values_only=True`. La cabecera es la fila 0 — este
    formato no lleva metadatos arriba, a diferencia del tradicional.
    """
    if not filas:
        return []
    cols = [normalizar_concepto(c) if c else "" for c in filas[0]]
    try:
        i_cod = cols.index("codigo")
        i_desc = cols.index("descripcion")
        i_pub = cols.index("fecha publicacion")
        i_ini = cols.index("fecha inicial")
        i_fin = cols.index("fecha final")
    except ValueError:
        return []

    identidad = {i_cod, i_desc, i_pub, i_ini, i_fin}
    objetivo = agente.strip().upper()
    salida: list[dict] = []
    for fila in filas[1:]:
        if not fila or len(fila) <= max(i_cod, i_desc, i_pub, i_ini, i_fin) or not fila[i_cod]:
            continue
        if str(fila[i_cod]).strip().upper() != objetivo:
            continue
        comp: dict[str, float] = {}
        for i in range(len(cols)):
            if i in identidad or not cols[i] or i >= len(fila):
                continue
            try:
                comp[cols[i]] = float(fila[i]) if fila[i] is not None else 0.0
            except (TypeError, ValueError):
                continue
        salida.append({
            "periodo": str(fila[i_desc]).strip() if fila[i_desc] else "",
            "fecha_publicacion": _fecha(fila[i_pub]),
            "periodo_ini": _fecha(fila[i_ini]),
            "periodo_fin": _fecha(fila[i_fin]),
            "componentes": comp,
        })
    return salida


def _etiqueta(nombre: str) -> str:
    u = nombre.upper()
    if "TX2" in u:
        return "AJUSTE TX2"
    if "M+1" in u or "M+ 1" in u:
        return "AJUSTE M+1"
    if "PROY" in u:
        return "AJUSTE PROY"
    return "AJUSTE"


def ventana_de_hoja(nombre: str, vencimiento: datetime.date
                    ) -> tuple[datetime.date, datetime.date, str] | None:
    """Formato TRADICIONAL: `AJUSTE TX2 SEMA MENS 01-07 AGO` + vto -> (ini, fin, etiqueta).

    El año no está en el nombre: se infiere del vencimiento y de la dirección de la
    hoja. `AJUSTE TX2` / `AJUSTE PROY` / `AJUSTE` miran hacia atrás: si el mes de la
    ventana es posterior al del vencimiento, la ventana es del año anterior — el caso
    de una hoja de DIC en un archivo de ENE. `AJUSTE M+1` mira hacia adelante — es el
    mes siguiente al vencimiento — así que la regla es la inversa: si el mes de la
    ventana es anterior al del vencimiento, la ventana es del año siguiente (el caso de
    un vencimiento de DIC con una hoja M+1 de ENE).
    """
    u = nombre.upper()
    if not u.startswith("AJUSTE"):
        return None
    m = _RE_VENTANA.search(u)
    if not m or m.group(3) not in _MESES:
        return None
    mes = _MESES[m.group(3)]
    etiqueta = _etiqueta(nombre)
    if etiqueta == "AJUSTE M+1":
        anio = vencimiento.year + 1 if mes < vencimiento.month else vencimiento.year
    else:
        anio = vencimiento.year - 1 if mes > vencimiento.month else vencimiento.year
    try:
        ini = datetime.date(anio, mes, int(m.group(1)))
        fin = datetime.date(anio, mes, int(m.group(2)))
    except ValueError:
        return None
    return ini, fin, etiqueta


def componentes_de_hoja(filas: list[tuple], agente: str) -> dict[str, float]:
    """Formato TRADICIONAL: componentes del agente en una hoja `AJUSTE …`.

    La cabecera se busca por la celda que contiene `CÓDIGO`: estos archivos traen 2 a 10
    filas de metadatos arriba y la posición varía entre vencimientos.
    """
    idx = None
    for i, fila in enumerate(filas):
        if fila and any(isinstance(c, str) and "CÓDIGO" in c.upper() for c in fila if c):
            idx = i
            break
    if idx is None:
        return {}

    cols = [normalizar_concepto(c) if c else "" for c in filas[idx]]
    objetivo = agente.strip().upper()
    for fila in filas[idx + 1:]:
        if not fila or not fila[0]:
            continue
        if str(fila[0]).strip().upper() != objetivo:
            continue
        salida: dict[str, float] = {}
        for i in range(1, min(len(cols), len(fila))):
            if not cols[i]:
                continue
            try:
                salida[cols[i]] = float(fila[i]) if fila[i] is not None else 0.0
            except (TypeError, ValueError):
                continue
        return salida
    return {}
