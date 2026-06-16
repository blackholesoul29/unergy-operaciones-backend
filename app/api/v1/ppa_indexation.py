"""Endpoints del motor de indexación de tarifas PPA.

Se monta bajo el router PPA (prefijo /ppa):
  GET  /ppa/{contract_id}/preview   → calcula sin persistir (sin cambios en DB)
  POST /ppa/{contract_id}/indexate  → calcula y persiste (upsert idempotente)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.schemas.ppa_indexation import IndexationSummary
from app.services.ppa_indexation import PPAIndexationService

logger = logging.getLogger(__name__)

# Sin prefijo propio: se incluye dentro del router PPA (que ya aporta /ppa).
router = APIRouter(tags=["PPA Indexación"])


@router.get("/{contract_id}/preview", response_model=IndexationSummary)
def preview_indexacion(
    contract_id: int,
    desde: str | None = Query(None, description="Periodo inicial YYYY-MM"),
    hasta: str | None = Query(None, description="Periodo final YYYY-MM"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Devuelve las tarifas calculadas SIN escribir en la base de datos."""
    service = PPAIndexationService(db)
    try:
        return service.calculate_tariffs(contract_id, desde, hasta)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("Error en preview de indexación PPA %s", contract_id)
        raise HTTPException(422, f"No se pudo calcular la indexación: {e}")


@router.post("/{contract_id}/indexate", response_model=IndexationSummary)
def ejecutar_indexacion(
    contract_id: int,
    desde: str | None = Query(None, description="Periodo inicial YYYY-MM"),
    hasta: str | None = Query(None, description="Periodo final YYYY-MM"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Calcula y persiste las tarifas del contrato (idempotente)."""
    service = PPAIndexationService(db)
    try:
        return service.calculate_and_persist(contract_id, desde, hasta)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        db.rollback()
        logger.exception("Error al indexar contrato PPA %s", contract_id)
        raise HTTPException(422, f"No se pudo indexar el contrato: {e}")
