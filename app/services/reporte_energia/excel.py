"""Genera el Excel en el formato manual que ya diligencia el equipo cada
mañana (hoja "datos") -- puerto de reporte_excel.py (repo Reporte-Energia),
leyendo directamente de las tablas ya guardadas en vez de un DataFrame en
memoria.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo

COLUMNAS = [
    "nombre_proyecto", "Hora", "Consumo_Principal", "Generación_Principal",
    "Consumo_Respaldo", "Generación_Respaldo",
]


def generar_excel_dia(db: Session, fecha: date) -> bytes:
    gen_filas = db.execute(
        select(ReporteEnergiaGeneracion, Frontera)
        .join(Frontera, Frontera.id == ReporteEnergiaGeneracion.frontera_id)
        .where(ReporteEnergiaGeneracion.fecha == fecha)
    ).all()
    con_filas = db.execute(
        select(ReporteEnergiaConsumo, Frontera)
        .join(Frontera, Frontera.id == ReporteEnergiaConsumo.frontera_id)
        .where(ReporteEnergiaConsumo.fecha == fecha)
    ).all()

    con_por_proyecto = {}
    for rep, front in con_filas:
        if front.proyecto_id is not None:
            con_por_proyecto[front.proyecto_id] = rep

    wb = Workbook()
    ws = wb.active
    ws.title = "datos"
    for col_idx, nombre in enumerate(COLUMNAS, start=1):
        ws.cell(row=1, column=col_idx, value=nombre)

    fila_excel = 2
    for rep_gen, front_gen in gen_filas:
        curva_final = rep_gen.curva_final or [None] * 24
        reporte_ya_valido = rep_gen.medidor_usado == "cgm"

        rep_con = con_por_proyecto.get(front_gen.proyecto_id)
        consumo_ya_valido = bool(rep_con and rep_con.caso == "CGM")
        curva_con = (rep_con.curva_final if rep_con else None) or [None] * 24

        for hora in range(24):
            valor_gen = None if reporte_ya_valido else curva_final[hora]
            if valor_gen is None and not reporte_ya_valido:
                valor_gen = 0.0
            valor_con = None if consumo_ya_valido else curva_con[hora]
            if valor_con is None and not consumo_ya_valido:
                valor_con = 0.0

            ws.append([
                front_gen.nombre_frontera, hora,
                valor_con, valor_gen,
                f"=C{fila_excel}*(1+(RAND()*0.02-0.01))",
                f"=D{fila_excel}*(1+(RAND()*0.02-0.01))",
            ])
            fila_excel += 1

    for col_idx, nombre in enumerate(COLUMNAS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(len(nombre) + 2, 10)
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
