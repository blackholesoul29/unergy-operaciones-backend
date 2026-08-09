"""Parsea el Excel que envía una empresa tercera para fronteras cuyo CGM lo
maneja esa empresa (FRONTERAS_TERCEROS, ver clasificador.py -- ej.
Cedillanos). Formato observado: una fila por (FECHA, ROLE), con columnas
CODIGO SIC | ROLE (Primary/Backup) | ENERGY TYPE | FECHA | HORA00..HORA23.

El CODIGO SIC del archivo se ignora deliberadamente -- puede traer el código
del tercero, no necesariamente el de nuestra frontera; qué frontera_id
recibe los datos lo decide la URL del endpoint, no el contenido del Excel.
"""
from __future__ import annotations

import io
from datetime import date

import openpyxl

_ENERGY_TYPE_OBJETIVO = "ENERGIAEXPORTADAACTIVA"
_ACENTOS = str.maketrans("ÁÉÍÓÚÑ", "AEIOUN")


def _normalizar(valor) -> str:
    if valor is None:
        return ""
    return str(valor).strip().upper().translate(_ACENTOS).replace(" ", "")


def parse_excel_terceros(contenido: bytes) -> dict[date, dict]:
    """Retorna {fecha: {"principal": [24 floats|None] | None, "respaldo": [24 floats|None] | None}},
    filtrado a ENERGY TYPE == 'ENERGIA EXPORTADA ACTIVA'. Lanza ValueError con
    un mensaje apto para mostrar al usuario si el archivo no tiene el formato
    esperado."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"No se pudo leer el Excel: {e}")
    ws = wb[wb.sheetnames[0]]

    filas = ws.iter_rows(values_only=True)
    try:
        header = list(next(filas))
    except StopIteration:
        raise ValueError("El archivo está vacío")
    header_norm = [_normalizar(h) for h in header]

    def _find(*names):
        for i, h in enumerate(header_norm):
            if h in names:
                return i
        return None

    i_role = _find("ROLE")
    i_tipo = _find("ENERGYTYPE")
    i_fecha = _find("FECHA")
    if i_role is None or i_tipo is None or i_fecha is None:
        raise ValueError("El archivo debe tener columnas ROLE, ENERGY TYPE y FECHA")

    horas_idx: dict[int, int] = {}
    for i, h in enumerate(header_norm):
        if h.startswith("HORA") and h[4:].isdigit():
            horas_idx[int(h[4:])] = i
    if len(horas_idx) < 24:
        raise ValueError(f"Encontré {len(horas_idx)} columnas HORA00..HORA23, se esperaban 24")

    resultado: dict[date, dict] = {}
    for r in filas:
        if not r or i_tipo >= len(r) or _normalizar(r[i_tipo]) != _ENERGY_TYPE_OBJETIVO:
            continue

        fv = r[i_fecha] if i_fecha < len(r) else None
        if hasattr(fv, "date"):
            fecha = fv.date()
        elif hasattr(fv, "year"):
            fecha = fv
        else:
            try:
                fecha = date.fromisoformat(str(fv)[:10])
            except (ValueError, TypeError):
                continue

        role = _normalizar(r[i_role]) if i_role < len(r) else ""
        curva = [
            float(r[horas_idx[h]]) if horas_idx[h] < len(r) and r[horas_idx[h]] is not None else None
            for h in range(24)
        ]

        dia = resultado.setdefault(fecha, {"principal": None, "respaldo": None})
        if role == "PRIMARY":
            dia["principal"] = curva
        elif role == "BACKUP":
            dia["respaldo"] = curva

    return resultado
