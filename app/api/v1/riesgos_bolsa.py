"""Endpoints del módulo Descubrimientos y Gestión de Riesgos de Bolsa."""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.schemas.riesgos_bolsa import (
    IngestPrecioBolsaRequest, IngestResult,
    ExposureResult, HistoricalExposureOut,
    ProjectedExposureInput, ProjectedExposureOut,
    RiskIndicatorsOutput,
)
from app.services import riesgos_bolsa as svc
from app.utils.xm_parser import parse_xm_precio_bolsa, XMPrecioBolsaParseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/riesgos-bolsa", tags=["Riesgos Bolsa"])


@router.post("/ingest-precio-bolsa", response_model=IngestResult)
def ingest_precio_bolsa(
    payload: IngestPrecioBolsaRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Ingiere el precio de bolsa desde un archivo de XM (upsert por hora)."""
    try:
        filas = parse_xm_precio_bolsa(
            payload.file_path, convertir_kwh_a_mwh=payload.convertir_kwh_a_mwh
        )
    except FileNotFoundError:
        raise HTTPException(404, f"Archivo no encontrado: {payload.file_path}")
    except XMPrecioBolsaParseError as e:
        raise HTTPException(422, str(e))

    if not filas:
        raise HTTPException(422, "El archivo no contenía filas de precio de bolsa.")

    return IngestResult(**svc.bulk_upsert_precio_bolsa(db, filas))


@router.get("/exposure/current", response_model=ExposureResult)
def exposure_current(
    fecha: date | None = Query(None, description="Día a evaluar; por defecto el último con precio"),
    planta_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return svc.calculate_current_exposure(db, fecha=fecha, planta_id=planta_id)


@router.get("/exposure/historical", response_model=HistoricalExposureOut)
def exposure_historical(
    start_dt: date = Query(...),
    end_dt: date = Query(...),
    planta_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if end_dt < start_dt:
        raise HTTPException(422, "end_dt no puede ser anterior a start_dt.")
    return svc.get_historical_exposure(db, start_dt, end_dt, planta_id)


@router.post("/exposure/projected", response_model=ProjectedExposureOut)
def exposure_projected(
    payload: ProjectedExposureInput,
    _=Depends(get_current_user),
):
    precios = {p.fecha: p.precio_cop_mwh for p in payload.puntos}
    generaciones = {p.fecha: p.generacion_mwh for p in payload.puntos}
    obligaciones = {p.fecha: p.ppa_obligacion_mwh for p in payload.puntos}
    return svc.project_exposure_scenario(precios, generaciones, obligaciones)


@router.get("/risk-indicators", response_model=RiskIndicatorsOutput)
def risk_indicators(
    start_dt: date = Query(...),
    end_dt: date = Query(...),
    planta_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if end_dt < start_dt:
        raise HTTPException(422, "end_dt no puede ser anterior a start_dt.")
    return svc.get_risk_indicators(db, start_dt, end_dt, planta_id)
