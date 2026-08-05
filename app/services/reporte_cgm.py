"""Generación del reporte CGM (extracción Quoia + Excel formato ASIC).

Puerto del script standalone `enviar_reporte_cgm.py` (repo ReporteCGM), pero
acotado a un conjunto específico de fronteras en vez de recorrer todo el
catálogo de Quoia -- el llamador decide qué frt_codes pedir.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from app.services.mgs.gaia_client import GaiaClient

HORAS = list(range(24))

_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def es_ultimo_dia_del_mes(fecha: date) -> bool:
    return fecha.day == calendar.monthrange(fecha.year, fecha.month)[1]


def dias_del_mes(fecha: date) -> list[str]:
    """Del día 1 al día `fecha` (inclusive, mismo mes) -- para el consolidado
    mensual que se adjunta cuando `fecha` es el último día del mes."""
    inicio = fecha.replace(day=1)
    return [(inicio + timedelta(days=i)).isoformat() for i in range((fecha - inicio).days + 1)]


def nombre_mes(fecha: date) -> str:
    return _MESES_ES[fecha.month - 1]


def titulo_hoja_mensual(fecha: date) -> str:
    return f"Consolidado {_MESES_ES[fecha.month - 1].capitalize()} {fecha.year}"

ESTADO_QUOIA = {
    "OK": "Exitoso",
    "WARNING": "Exitoso con novedades",
    "ERROR": "Fallo en validacion",
}
CATEGORIA = {1: "Frontera de generación", 2: "Frontera de generación - Consumo"}

COLUMNAS = (
    ["report date", "border frtcode", "border sic code", "border category", "meter", "state"]
    + [f"hour {h}" for h in HORAS]
    + ["total reported energy"]
)


def resolver_borders(gaia: GaiaClient, frt_codes: set[str]) -> dict[str, dict]:
    """Mapea frt_code (lowercase) -> {id, category, name} usando el listado de
    Quoia (get_all_borders, ya cacheado 1h) -- solo para los frt_codes pedidos."""
    wanted = {c.lower() for c in frt_codes}
    resultado: dict[str, dict] = {}
    for proyecto in gaia.get_all_borders():
        nombre = (proyecto.get("name") or "").strip()
        for key in ("frt_generation", "frt_consumption"):
            frt = proyecto.get(key)
            if not frt:
                continue
            frt_code = (frt.get("frt_code") or "").strip().lower()
            if frt_code in wanted:
                resultado[frt_code] = {
                    "id": frt.get("id"),
                    "category": frt.get("category"),
                    "name": nombre,
                }
    return resultado


def fetch_filas(gaia: GaiaClient, frt_code: str, border_meta: dict | None, fecha_str: str) -> list[dict]:
    """Filas main/backup (24h + total) para una frontera. border_meta viene de
    resolver_borders(); si es None (frt_code no encontrado en Quoia hoy),
    retorna filas en cero con estado "Sin reporte"."""
    nombre = border_meta.get("name", "") if border_meta else ""
    categoria = CATEGORIA.get(border_meta.get("category") if border_meta else None, "Frontera de generación")
    border_id = border_meta.get("id") if border_meta else None

    reporte = gaia.get_border_report_status(border_id, fecha_str) if border_id else None
    if reporte:
        estado = ESTADO_QUOIA.get(str(reporte.get("status", "")).upper(), "Sin reporte")
        main_curva = reporte.get("reported_data_main") or [0.0] * 24
        back_curva = reporte.get("reported_data_backup") or [0.0] * 24
    else:
        estado = "Sin reporte"
        main_curva = [0.0] * 24
        back_curva = [0.0] * 24

    filas = []
    for meter_label, curva in [("main", main_curva), ("backup", back_curva)]:
        fila = {
            "report date": fecha_str,
            "border frtcode": frt_code,
            "border sic code": nombre,
            "border category": categoria,
            "meter": meter_label,
            "state": estado,
        }
        for h in HORAS:
            fila[f"hour {h}"] = round(float(curva[h]), 3) if h < len(curva) else 0.0
        fila["total reported energy"] = round(sum(float(v) for v in curva), 3)
        filas.append(fila)
    return filas


def _estilo_encabezado(cell):
    cell.font = Font(bold=True, size=9)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    borde = Side(style="thin", color="000000")
    cell.border = Border(left=borde, right=borde, top=borde, bottom=borde)


def _estilo_dato(cell):
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.font = Font(size=9)
    borde = Side(style="thin", color="D0D0D0")
    cell.border = Border(left=borde, right=borde, top=borde, bottom=borde)


_ANCHOS_COLUMNA = {
    "report date": 12, "border frtcode": 14, "border sic code": 30,
    "border category": 30, "meter": 8, "state": 22,
    "total reported energy": 18,
}


def _escribir_hoja(ws, filas: list[dict]) -> None:
    for col_idx, nombre in enumerate(COLUMNAS, start=1):
        _estilo_encabezado(ws.cell(row=1, column=col_idx, value=nombre))

    for row_idx, fila in enumerate(filas, start=2):
        for col_idx, col in enumerate(COLUMNAS, start=1):
            valor = fila.get(col)
            if isinstance(valor, float):
                valor = round(valor, 3)
            _estilo_dato(ws.cell(row=row_idx, column=col_idx, value=valor))

    for col_idx, nombre in enumerate(COLUMNAS, start=1):
        letra = get_column_letter(col_idx)
        ws.column_dimensions[letra].width = _ANCHOS_COLUMNA.get(nombre, 8 if nombre.startswith("hour") else 12)

    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 30


def generar_excel(filas: list[dict], titulo_hoja: str = "CGM Report") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = titulo_hoja[:31]  # límite de Excel para el nombre de hoja
    _escribir_hoja(ws, filas)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
