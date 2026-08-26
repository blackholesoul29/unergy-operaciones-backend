"""Validación de esquema de los archivos de XM.

Corre ANTES de que nada entre a `xm_medida`. Atrapa el caso real de abril-2026, en que
`dspcttos` y `BalCttos` llegaron con columnas duplicadas y desplazadas: sin esto, la
exposición cambia de signo y ningún error se lanza.
"""
from __future__ import annotations

import re

from app.services.garantias_modelo.normalizar import normalizar_concepto
from app.services.garantias_modelo.parsers_ftp import decodificar

_RE_HORA = re.compile(r"^(HORA|DESP_HORA|TRF_HORA)\s*\d{1,2}$", re.IGNORECASE)

# Columnas de identidad esperadas ANTES del bloque horario, por tipo — en orden.
# Se comparan por nombre Y posición (normalizando tildes/mayúsculas) para que un
# reorden con el mismo conteo de columnas (p.ej. CONCEPTO y MERCADO intercambiados)
# no pase como si fuera un archivo válido: `parsear_balcttos` asume posiciones fijas.
_IDENTIDAD = {
    "balcttos": ["CONCEPTO", "MERCADO", "CÓDIGO CONTRATO", "COMPRADOR", "VENDEDOR",
                 "TIPO DE DESPACHO", "TIPO ASIGNA"],
    "trsd": ["CODIGO", "CONTENIDO"],
    "dspcttos": ["CONTRATO", "VENDEDOR", "COMPRADOR", "TIPO", "TIPOMERC", "TIPO ASIGNA"],
}
_HORAS_ESPERADAS = {"balcttos": 24, "trsd": 24, "dspcttos": 48}  # dspcttos: DESP + TRF

# `arrpas` no es horario y cambió de layout el 2026-03-08 (Hallazgo D): 403 archivos
# históricos vienen sin AGENTE y 134 desde esa fecha lo traen antepuesto. Se aceptan
# ambos; cualquier otra cabecera se rechaza (fallar cerrado, Hallazgo B).
_ARRPAS_LAYOUTS = [
    ["SUBMERCADO"],
    ["AGENTE", "SUBMERCADO"],
]


def _normalizados(cols: list[str]) -> list[str]:
    return [normalizar_concepto(c) for c in cols]


def _validar_arrpas(cols: list[str]) -> tuple[bool, dict]:
    normalizados = _normalizados(cols)
    for identidad in _ARRPAS_LAYOUTS:
        n = len(identidad)
        if normalizados[:n] == _normalizados(identidad) and len(cols) > n:
            return True, {"columnas": len(cols), "valores": len(cols) - n}
    return False, {
        "motivo": f"cabecera de arrpas no coincide con ningún layout conocido: {cols}",
        "columnas": len(cols),
    }


def validar_estructura(contenido: bytes, tipo: str) -> tuple[bool, dict]:
    """(ok, detalle). `detalle` va tal cual a `xm_archivo.esquema_detalle`."""
    texto = decodificar(contenido)
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return False, {"motivo": "archivo vacío"}

    cols = [c.strip() for c in lineas[0].split(";")]

    dups = {c for c in cols if c and cols.count(c) > 1}
    if dups:
        return False, {
            "motivo": f"columnas duplicadas: {sorted(dups)}",
            "columnas": len(cols),
        }

    if tipo == "arrpas":
        return _validar_arrpas(cols)

    identidad = _IDENTIDAD.get(tipo)
    if identidad is None:
        # Fallar cerrado: un tipo no dado de alta no debe pasar solo porque no
        # hay reglas para él.
        return False, {"motivo": f"tipo desconocido: {tipo!r}", "columnas": len(cols)}

    n = len(identidad)
    prefijo = cols[:n]
    if _normalizados(prefijo) != _normalizados(identidad):
        return False, {
            "motivo": (f"columnas de identidad no coinciden: se esperaba {identidad} "
                       f"en las primeras {n} posiciones y hay {prefijo}"),
            "columnas": len(cols),
        }

    resto = cols[n:]
    horas = [c for c in resto if _RE_HORA.match(c)]
    esperadas = _HORAS_ESPERADAS[tipo]
    if len(horas) != esperadas or len(horas) != len(resto):
        return False, {
            "motivo": f"se esperaban {esperadas} columnas horarias y hay {len(horas)}",
            "horas_encontradas": len(horas),
            "columnas": len(cols),
        }

    return True, {"columnas": len(cols), "horas": len(horas), "filas": len(lineas) - 1}


def verificar_identidad_balcttos(*, generacion_ideal: float, contratos_venta: float,
                                 perdidas: float, neto_ventas: float,
                                 neto_compras: float,
                                 tolerancia: float = 0.01) -> tuple[bool, float]:
    """`GI − contratos − pérdidas == ventas − compras`.

    Verificada al centavo sobre datos reales en 526 de 538 días. No cierra en el 2%
    restante, así que el día se marca — no se descarta en silencio ni se acepta callado.
    """
    izq = generacion_ideal - contratos_venta - perdidas
    der = neto_ventas - neto_compras
    residuo = izq - der
    return abs(residuo) < tolerancia, residuo
