"""Acceso a datos de ``LiquidacionXMIngesta`` (salida de la automatización).

Es la única capa que toca la tabla ``liquidacion_xm_ingesta``. El orquestador y
la API la usan en lugar de emitir queries sueltas, para que la lógica de
idempotencia (borrar+insertar por informe) viva en un solo sitio.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.liquidaciones import LiquidacionXMIngesta
from app.schemas.liquidaciones import LiquidacionXMIngestaCreate


def create_liquidacion_dato(db: Session, dato: LiquidacionXMIngestaCreate) -> LiquidacionXMIngesta:
    """Inserta una fila. No hace commit — el llamador controla la transacción."""
    obj = LiquidacionXMIngesta(**dato.model_dump())
    db.add(obj)
    db.flush()
    return obj


def bulk_create_liquidacion_datos(
    db: Session, datos: list[LiquidacionXMIngestaCreate]
) -> list[LiquidacionXMIngesta]:
    """Inserta muchas filas de una vez. No hace commit."""
    objs = [LiquidacionXMIngesta(**d.model_dump()) for d in datos]
    db.add_all(objs)
    db.flush()
    return objs


def get_liquidaciones_by_informe_id(db: Session, informe_id: int) -> list[LiquidacionXMIngesta]:
    """Todas las filas de un informe, ordenadas por proyecto y fecha."""
    stmt = (
        select(LiquidacionXMIngesta)
        .where(LiquidacionXMIngesta.informe_id == informe_id)
        .order_by(
            LiquidacionXMIngesta.proyecto_id,
            LiquidacionXMIngesta.fecha,
            LiquidacionXMIngesta.hora,
        )
    )
    return list(db.execute(stmt).scalars().all())


def delete_by_informe_id(db: Session, informe_id: int) -> int:
    """Borra las filas de un informe (para reprocesar de forma idempotente).

    No hace commit. Devuelve la cantidad de filas borradas.
    """
    filas = (
        db.query(LiquidacionXMIngesta)
        .filter(LiquidacionXMIngesta.informe_id == informe_id)
        .delete(synchronize_session=False)
    )
    return filas
