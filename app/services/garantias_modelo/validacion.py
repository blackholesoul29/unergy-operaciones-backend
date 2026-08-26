"""Validación de esquema de los archivos de XM.

Corre ANTES de que nada entre a `xm_medida`. Atrapa el caso real de abril-2026, en que
`dspcttos` y `BalCttos` llegaron con columnas duplicadas y desplazadas: sin esto, la
exposición cambia de signo y ningún error se lanza.
"""
from __future__ import annotations

import re

from app.services.garantias_modelo.parsers_ftp import decodificar

_RE_HORA = re.compile(r"^(HORA|DESP_HORA|TRF_HORA)\s*\d{1,2}$", re.IGNORECASE)

# Columnas de identidad esperadas antes del bloque horario, por tipo.
_IDENTIDAD = {
    "balcttos": 7,
    "trsd": 2,
    "dspcttos": 6,
}
_HORAS_ESPERADAS = {"balcttos": 24, "trsd": 24, "dspcttos": 48}  # dspcttos: DESP + TRF


def validar_estructura(contenido: bytes, tipo: str) -> tuple[bool, dict]:
    """(ok, detalle). `detalle` va tal cual a `xm_archivo.esquema_detalle`."""
    texto = decodificar(contenido)
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return False, {"motivo": "archivo vacío"}

    cols = [c.strip() for c in lineas[0].split(";")]
    horas = [c for c in cols if _RE_HORA.match(c)]

    dups = {c for c in cols if c and cols.count(c) > 1}
    if dups:
        return False, {
            "motivo": f"columnas duplicadas: {sorted(dups)}",
            "columnas": len(cols),
        }

    esperadas = _HORAS_ESPERADAS.get(tipo)
    if esperadas is not None and len(horas) != esperadas:
        return False, {
            "motivo": f"se esperaban {esperadas} columnas horarias y hay {len(horas)}",
            "horas_encontradas": len(horas),
            "columnas": len(cols),
        }

    identidad = _IDENTIDAD.get(tipo)
    if identidad is not None and len(cols) - len(horas) != identidad:
        return False, {
            "motivo": (f"se esperaban {identidad} columnas de identidad y hay "
                       f"{len(cols) - len(horas)}"),
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
