"""Saldo vivo de garantías — el valor que realmente queda tras los movimientos.

`Garantia.valor_cop` es el valor CONSTITUIDO y nunca se actualiza: `create_movimiento`
deja el saldo corriente únicamente en `GarantiaMovimiento.saldo_posterior_cop`. Leer
`valor_cop` como si fuera el saldo disponible SOBREESTIMA la cobertura después de un
`cobro_xm` y esconde garantías en déficit.

El orden del último movimiento replica exactamente el del escritor
(`create_movimiento`): `fecha DESC, id DESC`.
"""
from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.garantias import GarantiaMovimiento


def saldos_posteriores(db: Session, garantia_ids: Iterable[int]) -> Dict[int, Optional[float]]:
    """`saldo_posterior_cop` del último movimiento de cada garantía, en una sola query.

    Solo incluye garantías con al menos un movimiento. El valor puede ser `None` si
    ese movimiento no dejó saldo registrado (filas viejas).
    """
    ids = [i for i in garantia_ids if i is not None]
    if not ids:
        return {}

    ultimo = (
        select(
            GarantiaMovimiento.garantia_id.label("garantia_id"),
            GarantiaMovimiento.saldo_posterior_cop.label("saldo_posterior_cop"),
            func.row_number()
            .over(
                partition_by=GarantiaMovimiento.garantia_id,
                order_by=(GarantiaMovimiento.fecha.desc(), GarantiaMovimiento.id.desc()),
            )
            .label("rn"),
        )
        .where(GarantiaMovimiento.garantia_id.in_(ids))
        .subquery()
    )

    filas = db.query(ultimo.c.garantia_id, ultimo.c.saldo_posterior_cop).filter(ultimo.c.rn == 1).all()
    return {
        gid: (float(saldo) if saldo is not None else None)
        for gid, saldo in filas
    }


def saldo_vivo(valor_cop, saldo_posterior: Optional[float], tiene_movimiento: bool) -> float:
    """Saldo disponible de UNA garantía.

    Sin movimientos (o con un último movimiento sin saldo registrado) el saldo vivo es
    el valor constituido — el mismo fallback que usa `create_movimiento` para arrancar
    el saldo corriente.
    """
    base = float(valor_cop) if valor_cop is not None else 0.0
    if not tiene_movimiento or saldo_posterior is None:
        return base
    return float(saldo_posterior)


def saldos_vivos(db: Session, garantias) -> Dict[int, float]:
    """Mapa `garantia_id -> saldo vivo` para una colección de garantías. Una sola query."""
    posteriores = saldos_posteriores(db, [g.id for g in garantias])
    return {
        g.id: saldo_vivo(g.valor_cop, posteriores.get(g.id), g.id in posteriores)
        for g in garantias
    }
