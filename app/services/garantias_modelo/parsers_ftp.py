"""Insumos horarios anchos de XM → formato largo.

Puro: recibe bytes, devuelve list[dict] lista para `xm_medida`. No toca la base.

Encoding: utf-8-sig con fallback a latin1. No es decorativo — los BalCttos reales
fallan en utf-8 por la tilde de PÉRDIDAS.
"""
from __future__ import annotations

import datetime

from app.services.garantias_modelo.normalizar import normalizar_concepto

HORAS = 24


def decodificar(contenido: bytes) -> str:
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("latin1")


def _valor(texto: str) -> float:
    t = (texto or "").strip().replace(",", ".")
    if not t:
        return 0.0
    try:
        return float(t)
    except ValueError:
        return 0.0


def _parsear_ancho(contenido: bytes, fecha: datetime.date, version: str | None,
                   tipo: str, entidad: str, col_concepto: int,
                   primera_hora: int) -> tuple[list[dict], int]:
    """Forma común: `col_concepto` identifica la serie y las 24 columnas desde
    `primera_hora` son las horas.

    Devuelve `(filas, descartadas)`. Una fila con menos columnas de las esperadas se
    descarta (no se lanza excepción: una fila malformada no debe abortar todo el
    archivo), pero se cuenta — perderla en silencio es indistinguible, río abajo, de
    que el concepto simplemente no tuvo exposición ese día.
    """
    filas: list[dict] = []
    descartadas = 0
    lineas = decodificar(contenido).splitlines()
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < primera_hora + HORAS:
            descartadas += 1
            continue
        crudo = (col[col_concepto] or "").strip()
        if not crudo:
            continue
        concepto = normalizar_concepto(crudo)
        for h in range(HORAS):
            filas.append({
                "tipo": tipo,
                "fecha_documento": fecha,
                "hora": h + 1,
                "entidad": entidad,
                "concepto": concepto,
                "concepto_raw": crudo[:200],
                "valor": _valor(col[primera_hora + h]),
                "version": version,
            })
    return filas, descartadas


def parsear_balcttos(contenido: bytes, fecha: datetime.date, version: str | None,
                     entidad: str) -> tuple[list[dict], int]:
    """`CONCEPTO;MERCADO;CÓDIGO CONTRATO;COMPRADOR;VENDEDOR;TIPO DESPACHO;TIPO ASIGNA;HORA 01..24`"""
    return _parsear_ancho(contenido, fecha, version, "balcttos", entidad,
                          col_concepto=0, primera_hora=7)


def parsear_trsd(contenido: bytes, fecha: datetime.date,
                 version: str | None) -> tuple[list[dict], int]:
    """`CODIGO;CONTENIDO;HORA 01..24`. Es nacional, no por agente."""
    return _parsear_ancho(contenido, fecha, version, "trsd", "NACIONAL",
                          col_concepto=0, primera_hora=2)


def parsear_dspcttos(contenido: bytes, fecha: datetime.date, version: str | None,
                     agente: str) -> tuple[list[dict], int]:
    """`CONTRATO;VENDEDOR;COMPRADOR;TIPO;TIPOMERC;TIPO ASIGNA;DESP_HORA 01..24;TRF_HORA 01..24`

    Es por contrato bilateral, no por planta. La entidad es el contrato; se filtra a
    las filas donde el agente es el vendedor. Solo se ingiere el bloque de despacho:
    la tarifa no entra en la identidad de exposición.

    Devuelve `(filas, descartadas)` — ver `_parsear_ancho` para el porqué de contar
    en vez de solo descartar.
    """
    filas: list[dict] = []
    descartadas = 0
    for linea in decodificar(contenido).splitlines()[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < 6 + HORAS:
            descartadas += 1
            continue
        if (col[1] or "").strip().upper() != agente.upper():
            continue
        contrato = (col[0] or "").strip()
        for h in range(HORAS):
            filas.append({
                "tipo": "dspcttos",
                "fecha_documento": fecha,
                "hora": h + 1,
                "entidad": contrato,
                "concepto": "despacho",
                "concepto_raw": "DESP_HORA",
                "valor": _valor(col[6 + h]),
                "version": version,
            })
    return filas, descartadas


def parsear_arrpas(contenido: bytes, fecha: datetime.date,
                   version: str | None) -> tuple[list[dict], int]:
    """`arrpas` es plano por submercado, no horario: una fila por submercado y columna.

    La entidad es el submercado y el concepto es el nombre de la columna. `hora` va en
    **0**, el centinela de "no horaria": con NULL, Postgres no considera iguales dos
    filas en un UNIQUE y estas medidas se duplicarían en silencio.

    Dos layouts conviven en el corpus real: el clásico `SUBMERCADO;...` y, desde
    2026-03-08, `AGENTE;SUBMERCADO;...` con el agente antepuesto. Se detecta por la
    cabecera — asumir siempre `col[0]` como submercado lee el agente como si fuera el
    submercado en los archivos nuevos. El agente no se conserva: la serie es por
    submercado, no se pidió agregar una columna nueva para el agente.

    Devuelve `(filas, descartadas)` — ver `_parsear_ancho` para el porqué de contar
    en vez de solo descartar.
    """
    filas: list[dict] = []
    descartadas = 0
    lineas = decodificar(contenido).splitlines()
    if not lineas:
        return filas, descartadas
    cabecera = [c.strip() for c in lineas[0].split(";")]
    if cabecera and normalizar_concepto(cabecera[0]) == normalizar_concepto("AGENTE"):
        col_submercado = 1
    else:
        col_submercado = 0
    primer_valor = col_submercado + 1
    minimo_columnas = primer_valor + 1
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < minimo_columnas:
            descartadas += 1
            continue
        submercado = (col[col_submercado] or "").strip()
        if not submercado:
            continue
        for i in range(primer_valor, min(len(col), len(cabecera))):
            crudo = cabecera[i]
            if not crudo:
                continue
            filas.append({
                "tipo": "arrpas",
                "fecha_documento": fecha,
                "hora": 0,
                "entidad": submercado,
                "concepto": normalizar_concepto(crudo),
                "concepto_raw": crudo[:200],
                "valor": _valor(col[i]),
                "version": version,
            })
    return filas, descartadas
