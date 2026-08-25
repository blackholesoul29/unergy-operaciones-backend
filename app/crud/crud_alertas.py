"""Operaciones CRUD sobre la tabla `alertas` (alertas persistentes)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.alerta import Alerta
from app.schemas.alerta import AlertaCreate


def create_alerta(db: Session, alerta: AlertaCreate) -> Alerta:
    """Persiste una nueva alerta y la devuelve con sus campos generados."""
    db_alerta = Alerta(**alerta.model_dump())
    db.add(db_alerta)
    db.commit()
    db.refresh(db_alerta)
    return db_alerta


def get_alerta_by_ppa_and_days(db: Session, ppa_id: int, days: int) -> Optional[Alerta]:
    """Devuelve la alerta existente para ese PPA y ventana (o None).

    Es el chequeo de idempotencia del job: junto con la restriccion unica
    (ppa_id, days_to_expiration) evita duplicar la alerta de una misma ventana.
    """
    return (
        db.query(Alerta)
        .filter(Alerta.ppa_id == ppa_id, Alerta.days_to_expiration == days)
        .first()
    )


def update_alerta_status(db: Session, alerta_id: int, status: str) -> Optional[Alerta]:
    """Actualiza el estado de una alerta. Devuelve la alerta o None si no existe."""
    db_alerta = db.query(Alerta).filter(Alerta.id == alerta_id).first()
    if db_alerta is None:
        return None
    db_alerta.status = status
    db.commit()
    db.refresh(db_alerta)
    return db_alerta
