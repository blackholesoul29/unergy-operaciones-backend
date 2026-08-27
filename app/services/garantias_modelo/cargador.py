"""Carga de insumos de XM a `xm_archivo` + `xm_medida`.

La idempotencia es por `sha256` del contenido en `xm_archivo` y por la clave natural en
`xm_medida`. Reingerir el mismo corpus no duplica filas.
"""
from __future__ import annotations

import datetime

# Días entre la fecha del documento y el momento en que esa versión está disponible.
#
# El de `tx2` no es una suposición: sale del timeline que XM declara. Para el
# vencimiento del 28-AGO la ventana base cierra el 14-AGO y XM calcula el 21-AGO usando
# datos en versión TX2 de esos días — luego un `.tx2` del día D está disponible a más
# tardar D+7.
#
# Errar por exceso es seguro: un lag más grande solo EXCLUYE datos que sí estaban
# disponibles y hace el backtest pesimista. Uno más chico FILTRA datos que no existían e
# invalida el backtest sin que nada falle. Ante la duda, agrandar.
LAG_POR_VERSION = {
    "tx2": 7,
}


def disponible_desde_derivado(fecha_documento: datetime.date,
                              version: str) -> datetime.datetime:
    """`fecha_documento + lag`, en UTC. Falla si la versión no tiene lag conocido.

    No hay valor por defecto a propósito: inventar un lag para una versión que no
    medimos es exactamente el error que este diseño evita.
    """
    lag = LAG_POR_VERSION.get((version or "").lower())
    if lag is None:
        raise ValueError(
            f"sin lag conocido para la versión {version!r}: no se puede derivar "
            f"disponible_desde. Agregarlo a LAG_POR_VERSION solo con evidencia.")
    return datetime.datetime.combine(
        fecha_documento + datetime.timedelta(days=lag),
        datetime.time.min,
        tzinfo=datetime.timezone.utc,
    )


# Las columnas de `uq_xm_medida_natural`, en orden.
CLAVE_NATURAL = ("tipo", "fecha_documento", "hora", "entidad", "concepto", "version")


def agregar_por_clave_natural(filas: list[dict]) -> tuple[list[dict], int]:
    """Colapsa las filas que comparten la clave natural, sumando el valor.

    Hace falta porque **BalCttos trae una línea por contrato**: en un día de enero-2025
    `CONTRATO DE VENTA` aparece 8 veces y en julio-2026, 50. Como el parser identifica
    la serie por `CONCEPTO` y descarta `CÓDIGO CONTRATO`, esas líneas comparten la clave
    natural y el INSERT choca contra `uq_xm_medida_natural`.

    Sumar es lo correcto y no pierde información:

    - Los tres conceptos que usa la réplica (`neto de compras en bolsa`,
      `neto de ventas en bolsa`, `pbna`) aparecen **una sola vez** por día, así que la
      agregación ni los toca.
    - El único que se repite es `contrato de venta`, y su total es justamente lo que se
      concilia contra `dspcttos`.
    - El detalle por contrato sigue disponible en `dspcttos`, donde `concepto` ES el
      código de contrato y por lo tanto no colisiona.

    Devuelve `(filas, colapsadas)`. El conteo se devuelve para poder reportarlo: agregar
    en silencio sería otra transformación invisible, del mismo tipo que este proyecto ya
    viene atrapando.
    """
    acum: dict[tuple, dict] = {}
    colapsadas = 0
    for f in filas:
        k = tuple(f.get(c) for c in CLAVE_NATURAL)
        previo = acum.get(k)
        if previo is None:
            acum[k] = dict(f)
        else:
            previo["valor"] = float(previo["valor"]) + float(f["valor"])
            colapsadas += 1
    return list(acum.values()), colapsadas


def filas_a_medidas(filas: list[dict], *, archivo_id: int) -> list[dict]:
    """Anexa `archivo_id` a las filas que devolvió un parser, listas para `xm_medida`."""
    return [dict(f, archivo_id=archivo_id) for f in filas]
