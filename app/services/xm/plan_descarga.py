"""Construcción del plan de descarga de archivos XM para un rango de fechas."""

import calendar
from datetime import date

from app.services.xm.tipos import validar_tipo, es_mensual, nombre_archivo, ruta_directorio


def construir_plan_descarga(tipo: str, extension: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    """Expande un rango de fechas en la lista de archivos a intentar descargar.

    Cada item: {anio, mes, dia, directorio, nombre_archivo, fecha_documento}.
    `dia` es None para tipos mensuales (cxcsb). `fecha_documento` es
    'YYYY-MM-DD' para diarios o 'YYYY-MM' para mensuales.
    """
    validar_tipo(tipo)
    if fecha_fin < fecha_inicio:
        raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")

    plan = []
    mensual = es_mensual(tipo)
    anio, mes = fecha_inicio.year, fecha_inicio.month

    while (anio, mes) <= (fecha_fin.year, fecha_fin.month):
        directorio = ruta_directorio(tipo, anio, mes)
        if mensual:
            plan.append({
                "anio": anio, "mes": mes, "dia": None,
                "directorio": directorio,
                "nombre_archivo": nombre_archivo(tipo, extension, anio, mes),
                "fecha_documento": f"{anio:04d}-{mes:02d}",
            })
        else:
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            dia_desde = fecha_inicio.day if (anio, mes) == (fecha_inicio.year, fecha_inicio.month) else 1
            dia_hasta = fecha_fin.day if (anio, mes) == (fecha_fin.year, fecha_fin.month) else ultimo_dia
            for dia in range(dia_desde, dia_hasta + 1):
                plan.append({
                    "anio": anio, "mes": mes, "dia": dia,
                    "directorio": directorio,
                    "nombre_archivo": nombre_archivo(tipo, extension, anio, mes, dia),
                    "fecha_documento": f"{anio:04d}-{mes:02d}-{dia:02d}",
                })
        if mes == 12:
            anio, mes = anio + 1, 1
        else:
            mes += 1

    return plan
