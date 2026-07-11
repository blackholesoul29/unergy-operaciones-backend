"""Operaciones CRUD para `LiquidacionXMDatoIngesta` (tabla `liquidacion_xm_dato`).

El pipeline de ingesta deduplica por `hash_fila`: antes de insertar se consulta
`get_existing_hashes` con los hashes del lote y `create_multiple` omite los que ya
existen, de modo que reprocesar un mismo archivo es idempotente.
"""
from datetime import date
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.liquidacion_xm import LiquidacionXMDatoIngesta
from app.schemas.liquidacion_xm import LiquidacionXMDatoCreate


def get_by_hash(db: Session, hash_fila: str) -> Optional[LiquidacionXMDatoIngesta]:
    """Devuelve el registro con ese hash, o None si no existe."""
    return (
        db.query(LiquidacionXMDatoIngesta)
        .filter(LiquidacionXMDatoIngesta.hash_fila == hash_fila)
        .first()
    )


def get_existing_hashes(db: Session, hashes: Iterable[str]) -> set[str]:
    """Devuelve el subconjunto de `hashes` que ya está en la base de datos.

    Se consulta en lotes para no exceder el límite de parámetros de Postgres
    cuando el archivo trae decenas de miles de filas.
    """
    hashes = list(dict.fromkeys(h for h in hashes if h))
    if not hashes:
        return set()
    encontrados: set[str] = set()
    CHUNK = 5000
    for i in range(0, len(hashes), CHUNK):
        lote = hashes[i:i + CHUNK]
        rows = db.execute(
            select(LiquidacionXMDatoIngesta.hash_fila).where(
                LiquidacionXMDatoIngesta.hash_fila.in_(lote)
            )
        ).all()
        encontrados.update(r[0] for r in rows)
    return encontrados


def create_multiple(db: Session, datos: list[LiquidacionXMDatoCreate]) -> int:
    """Inserta en bloque los datos nuevos (omitiendo hashes ya existentes).

    Devuelve la cantidad de filas realmente insertadas. Deduplica tanto contra
    la base de datos como dentro del propio lote.
    """
    if not datos:
        return 0

    existentes = get_existing_hashes(db, (d.hash_fila for d in datos))
    vistos: set[str] = set()
    nuevos: list[dict] = []
    for d in datos:
        if d.hash_fila in existentes or d.hash_fila in vistos:
            continue
        vistos.add(d.hash_fila)
        nuevos.append(d.model_dump())

    if not nuevos:
        return 0

    db.bulk_insert_mappings(LiquidacionXMDatoIngesta, nuevos)
    db.commit()
    return len(nuevos)


def get_filtered(
    db: Session,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    codigo_recurso: Optional[str] = None,
    fuente_archivo: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[LiquidacionXMDatoIngesta], int]:
    """Consulta paginada con filtros. Devuelve (items, total)."""
    q = db.query(LiquidacionXMDatoIngesta)
    if start_date is not None:
        q = q.filter(LiquidacionXMDatoIngesta.fecha >= start_date)
    if end_date is not None:
        q = q.filter(LiquidacionXMDatoIngesta.fecha <= end_date)
    if codigo_recurso:
        q = q.filter(LiquidacionXMDatoIngesta.codigo_recurso == codigo_recurso)
    if fuente_archivo:
        q = q.filter(LiquidacionXMDatoIngesta.fuente_archivo == fuente_archivo)

    total = q.order_by(None).with_entities(func.count(LiquidacionXMDatoIngesta.id)).scalar() or 0
    items = (
        q.order_by(LiquidacionXMDatoIngesta.fecha.desc(), LiquidacionXMDatoIngesta.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return items, total


def get_status(db: Session) -> dict:
    """Metadatos de la última ingesta: timestamp, archivo y total de registros."""
    total = db.query(func.count(LiquidacionXMDatoIngesta.id)).scalar() or 0
    ultimo = (
        db.query(LiquidacionXMDatoIngesta)
        .order_by(LiquidacionXMDatoIngesta.fecha_ingesta.desc(), LiquidacionXMDatoIngesta.id.desc())
        .first()
    )
    return {
        "ultima_ingesta": ultimo.fecha_ingesta if ultimo else None,
        "fuente_archivo": ultimo.fuente_archivo if ultimo else None,
        "total_registros": total,
    }
