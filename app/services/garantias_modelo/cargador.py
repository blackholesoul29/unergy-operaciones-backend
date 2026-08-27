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


def filas_a_medidas(filas: list[dict], *, archivo_id: int) -> list[dict]:
    """Anexa `archivo_id` a las filas que devolvió un parser, listas para `xm_medida`."""
    return [dict(f, archivo_id=archivo_id) for f in filas]
