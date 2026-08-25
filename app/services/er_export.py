"""Genera el Estado de Resultados en Excel desde las líneas del Panel.

Conserva la estructura del ER que usan hoy: la tabla día por día arriba, los tres
bloques de totales debajo y el detalle por partícipe a la derecha. Lo que cambia
es que los valores van **calculados**: el archivo que genera la API viene con las
fórmulas sin evaluar, y por eso hoy hace falta LibreOffice para poder leerlo.
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

_MORADO = "2C2039"
_LILA = "F1EAF9"
_MONEDA = "#,##0"
_ENERGIA = "#,##0.00"
_TARIFA = "#,##0.0000"

# Las columnas de la tabla diaria, en orden, con su formato. "Ingresos brutos"
# repite la venta a propósito: en el ER de hoy son la misma columna dos veces.
_COLUMNAS_DIARIAS = [
    ("generacion_kwh", _ENERGIA),
    ("importacion_kwh", _ENERGIA),
    ("venta_kwh", _ENERGIA),
    ("venta_cop", _MONEDA),
    ("venta_cop", _MONEDA),
]

# Los bloques de totales, en el orden en que se leen en el ER.
BLOQUES = [
    ("comercializacion", "Ingresos y costos XM", "Total Comercialización"),
    ("ingresos", "Ingresos y costos", "Total Ingresos"),
    ("costos", "Costos operativos", "Total Costos Operativos fijos"),
]


def _titulo(ws, fila: int, texto: str) -> int:
    celda = ws.cell(fila, 3, texto)
    celda.font = Font(bold=True, color=_MORADO)
    celda.fill = PatternFill("solid", fgColor=_LILA)
    ws.cell(fila, 4).fill = PatternFill("solid", fgColor=_LILA)
    return fila + 1


def _tabla_diaria(ws, diario: list[dict[str, Any]], comercializador: str | None) -> int:
    """Las filas día por día con su TOTAL. Devuelve la primera fila libre."""
    com = comercializador or "Comercializador"
    encabezados = [
        "Fecha", "Generación (kWh)", "Importación (kWh)",
        f"{com} Venta bolsa (kwh)", f"{com} Venta bolsa ($)", "Ingresos brutos",
    ]
    for i, texto in enumerate(encabezados):
        celda = ws.cell(3, 3 + i, texto)
        celda.font = Font(bold=True, size=9, color=_MORADO)
        celda.alignment = Alignment(wrap_text=True, vertical="center")

    fila = 4
    for d in diario:
        ws.cell(fila, 3, d["fecha"])
        for i, (clave, formato) in enumerate(_COLUMNAS_DIARIAS):
            ws.cell(fila, 4 + i, d.get(clave, 0.0)).number_format = formato
        fila += 1

    ws.cell(fila, 3, "TOTAL").font = Font(bold=True)
    for i, (clave, formato) in enumerate(_COLUMNAS_DIARIAS):
        celda = ws.cell(fila, 4 + i, round(sum(d.get(clave, 0.0) for d in diario), 2))
        celda.font = Font(bold=True)
        celda.number_format = formato
    return fila + 3


def _bloques_totales(ws, lineas, fila: int) -> tuple[int, dict[str, float]]:
    """Los tres bloques de conceptos. Devuelve la fila libre y los subtotales."""
    subtotales: dict[str, float] = {}
    for clave, titulo, etiqueta_total in BLOQUES:
        del_bloque = [l for l in lineas if l.grupo == clave]
        # Las facturas de Unergy se leen dentro de costos operativos, como en el
        # ER de hoy: son cobros del mismo bloque.
        if clave == "costos":
            del_bloque = del_bloque + [l for l in lineas if l.grupo == "facturas"]
        if not del_bloque:
            subtotales[clave] = 0.0
            continue

        fila = _titulo(ws, fila, titulo)
        por_concepto: dict[str, float] = {}
        for l in del_bloque:
            por_concepto[l.concepto] = por_concepto.get(l.concepto, 0.0) + float(l.valor_cop or 0)

        subtotal = 0.0
        for concepto, valor in por_concepto.items():
            ws.cell(fila, 3, concepto)
            ws.cell(fila, 4, round(abs(valor), 2)).number_format = _MONEDA
            subtotal += abs(valor)
            fila += 1

        ws.cell(fila, 3, etiqueta_total).font = Font(bold=True)
        celda = ws.cell(fila, 4, round(subtotal, 2))
        celda.font = Font(bold=True)
        celda.number_format = _MONEDA
        subtotales[clave] = subtotal
        fila += 2

    ws.cell(fila, 3, "Total de costos operativos + Comercialización").font = Font(bold=True)
    celda = ws.cell(fila, 4, round(subtotales.get("costos", 0.0)
                                   + subtotales.get("comercializacion", 0.0), 2))
    celda.font = Font(bold=True)
    celda.number_format = _MONEDA
    return fila + 2, subtotales


def _bloque_participe(ws, lineas, subtotales: dict[str, float],
                      diario: list[dict[str, Any]], fila_inicio: int = 51) -> None:
    """El detalle del partícipe, en las columnas F y G como en el ER de hoy."""
    nombres = {l.inversionista_nombre for l in lineas if l.inversionista_nombre}
    nombre = next(iter(nombres)) if len(nombres) == 1 else "Proyecto (100%)"
    pct = next((float(l.porcentaje or 0) for l in lineas if l.porcentaje), 100.0)

    ingresos = subtotales.get("ingresos", 0.0)
    costos_xm = subtotales.get("comercializacion", 0.0)
    energia = round(sum(d.get("generacion_kwh", 0.0) for d in diario), 2)
    facturas = [l for l in lineas if l.grupo == "facturas"]
    cobros = sum(abs(float(l.valor_cop or 0)) for l in facturas)

    filas: list[tuple[str, float | None]] = [
        (nombre, None),
        ("Porcentaje participación", round(pct / 100, 4)),
        ("Energia", energia),
        ("Ingresos brutos", round(ingresos, 2)),
        ("Costos XM", round(costos_xm, 2)),
        ("Valor a pagar", round(ingresos - costos_xm, 2)),
    ]
    for i, l in enumerate(facturas, start=1):
        filas.append((f"{i}. {l.concepto}", round(abs(float(l.valor_cop or 0)), 2)))
    filas.append(("Factura UNERGY", round(cobros, 2)))

    fila = fila_inicio
    for etiqueta, valor in filas:
        celda = ws.cell(fila, 6, etiqueta)
        if valor is None:
            celda.font = Font(bold=True, color=_MORADO)
        else:
            v = ws.cell(fila, 7, valor)
            v.number_format = _MONEDA if abs(valor) > 100 else _TARIFA
        fila += 1

    # Tarifa bruta y neta: lo que recibe el partícipe por kWh, antes y después de
    # los cobros. Con energía en cero no se calculan (división por cero).
    if energia:
        fila += 1
        ws.cell(fila, 6, f"Tarifa {nombre}").font = Font(bold=True, color=_MORADO)
        ws.cell(fila + 1, 6, "Tarifa bruta")
        ws.cell(fila + 1, 7, round(ingresos / energia, 4)).number_format = _TARIFA
        ws.cell(fila + 2, 6, "Tarifa neta")
        ws.cell(fila + 2, 7,
                round((ingresos - costos_xm - cobros) / energia, 4)).number_format = _TARIFA


def generar_er_xlsx(panel, nombre_proyecto: str,
                    diario: list[dict[str, Any]] | None = None,
                    inversionista: str | None = None) -> bytes:
    """El ``.xlsx`` del período. Con ``inversionista``, solo la parte de esa persona."""
    lineas = list(panel.lineas)
    if inversionista:
        lineas = [l for l in lineas if l.inversionista_nombre == inversionista]
    diario = diario or []

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    ws["A1"] = nombre_proyecto
    ws["A1"].font = Font(bold=True, size=14, color=_MORADO)
    ws["A2"] = f"Período {panel.periodo}"
    ws["A2"].font = Font(size=10, color="666666")

    fila = _tabla_diaria(ws, diario, getattr(panel, "comercializador", None))
    fila, subtotales = _bloques_totales(ws, lineas, fila)
    _bloque_participe(ws, lineas, subtotales, diario)

    ws.column_dimensions["C"].width = 52
    for col in ("D", "E", "F", "G", "H"):
        ws.column_dimensions[col].width = 20

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
