"""Modelo Predictivo de Garantías: el plan de la semana y el detalle de un vencimiento.

Solo transporte. El contrato lo congeló el plan 1 y el frontend ya está en producción
consumiéndolo: no cambiar nombres de campo sin cambiar la vista.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services.garantias_modelo.servicio import construir_detalle, construir_plan

router = APIRouter(prefix="/garantias/modelo", tags=["Garantías · Modelo Predictivo"])


@router.get("/plan")
def get_plan(
    agente: str = Query("UNGG"),
    esquema: str = Query("semanal"),
    cuantil: float = Query(0.9, ge=0.5, le=0.99),
    horizonte: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lo que hay que reservar para los próximos vencimientos.

    `horizonte` se ignora cuando `esquema` es mensual — el frontend lo envía siempre.
    """
    return construir_plan(db, agente=agente, esquema=esquema,
                          cuantil=cuantil, horizonte=horizonte)


@router.get("/detalle/{id}")
def get_detalle(
    id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Cadena de cálculo, descomposición del ancho e insumos de un vencimiento."""
    return construir_detalle(db, id=id)
