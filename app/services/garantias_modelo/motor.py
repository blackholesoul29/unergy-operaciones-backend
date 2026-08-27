"""Motor de la réplica: lee la base con el filtro anti-leakage y calcula.

**El filtro anti-leakage es una sola condición y vive acá:**

    XMArchivo.disponible_desde <= calculo.fecha_calculo

Todo lo demás del diseño existe para que esa línea sea correcta. Si se relaja, el
backtest da resultados que se ven bien y son falsos — el único bug del proyecto que no
avisa.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.garantias_modelo import GarCalculo, XMArchivo, XMMedida
from app.services.garantias_modelo.replica import exposicion_periodo

HORAS = 24

# Conceptos y entidades, verificados contra archivos reales el 2026-08-27 sobre
# `BalCttos0101.tx2` y `trsd0101.tx2` — no son suposiciones. Si alguno no coincide, el
# motor devuelve 0.0 sin fallar, que es el peor resultado posible.
#
#   BalCttos.tx2 -> entidad "UNGG", horas 1..24, 24 filas por concepto. Conceptos
#   normalizados presentes: compras en bolsa / contrato de venta / generacion ideal /
#   neto de compras en bolsa / neto de ventas en bolsa /
#   perdidas asignadas a un generador / ventas en bolsa
#
#   trsd.tx2 -> entidad "NACIONAL", horas 1..24. `pbna` está entre los 33 códigos.
_NETO_COMPRAS = "neto de compras en bolsa"
_NETO_VENTAS = "neto de ventas en bolsa"
_PBNA = "pbna"


def _series(db: Session, *, tipo: str, concepto: str, entidad: str | None,
            desde: datetime.date, hasta: datetime.date,
            corte: datetime.date, version: str = "tx2"
            ) -> dict[datetime.date, list[float]]:
    """Serie horaria por día, filtrada por disponibilidad a `corte`."""
    q = (
        select(XMMedida.fecha_documento, XMMedida.hora, XMMedida.valor)
        .join(XMArchivo, XMMedida.archivo_id == XMArchivo.id)
        .where(
            XMMedida.tipo == tipo,
            XMMedida.concepto == concepto,
            XMMedida.version == version,
            XMMedida.fecha_documento >= desde,
            XMMedida.fecha_documento <= hasta,
            XMArchivo.esquema_ok.is_(True),
            XMArchivo.disponible_desde <= datetime.datetime.combine(
                corte, datetime.time.max, tzinfo=datetime.timezone.utc),
        )
    )
    if entidad is not None:
        q = q.where(XMMedida.entidad == entidad)

    salida: dict[datetime.date, list[float]] = {}
    for fecha, hora, valor in db.execute(q):
        salida.setdefault(fecha, [0.0] * HORAS)
        if 1 <= hora <= HORAS:
            salida[fecha][hora - 1] = float(valor)
    return salida


def exposicion_de_calculo(db: Session, calculo: GarCalculo) -> dict:
    """Exposición en COP del período de `calculo`, con el filtro anti-leakage aplicado.

    Devuelve también los días efectivamente usados: un período al que le faltan días
    produce un número menor, y eso hay que verlo, no descubrirlo después.
    """
    corte = calculo.fecha_calculo or calculo.fecha_vencimiento
    comun = dict(desde=calculo.periodo_ini, hasta=calculo.periodo_fin, corte=corte)

    compras = _series(db, tipo="balcttos", concepto=_NETO_COMPRAS,
                      entidad=calculo.agente, **comun)
    ventas = _series(db, tipo="balcttos", concepto=_NETO_VENTAS,
                     entidad=calculo.agente, **comun)
    precio = _series(db, tipo="trsd", concepto=_PBNA, entidad="NACIONAL", **comun)

    dias_completos = sorted(set(compras) & set(precio))
    esperados = (calculo.periodo_fin - calculo.periodo_ini).days + 1

    armado = {
        d: {"compras": compras[d],
            "ventas": ventas.get(d, [0.0] * HORAS),
            "precio": precio[d]}
        for d in dias_completos
    }
    return {
        "valor": exposicion_periodo(armado),
        "dias_usados": len(dias_completos),
        "dias_esperados": esperados,
        "completo": len(dias_completos) == esperados,
    }
