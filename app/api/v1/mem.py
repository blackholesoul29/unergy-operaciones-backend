"""
API del módulo MEM — ingesta de datos de XM (ASIC, precios de bolsa, GESCON).
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Usuario
from app.models.mem import MEMDatosASIC, MEMPrecioBolsa, MEMGesconEstado
from app.services.mem_ingestion_service import MEMIngestionService
from app.schemas.mem import (
    IngestionSummary, MEMDatosASICOut, MEMPrecioBolsaOut,
    GesconEstadoUpdate, MEMGesconEstadoOut,
)

router = APIRouter(prefix="/mem", tags=["MEM"])

_WRITE_ROLES = ("admin", "liquidaciones", "operaciones")


def _require_mem_write(current: Usuario = Depends(get_current_user)) -> Usuario:
    if current.rol.value not in _WRITE_ROLES:
        raise HTTPException(403, "Se requiere rol admin, liquidaciones u operaciones")
    return current


# ── Ingesta ──────────────────────────────────────────────────────────────────

@router.post("/ingest/asic", response_model=IngestionSummary)
async def ingest_asic(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(_require_mem_write),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")
    summary = MEMIngestionService(db).ingest_asic_data(content, file.filename)
    return summary


@router.post("/ingest/precios", response_model=IngestionSummary)
async def ingest_precios(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(_require_mem_write),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")
    summary = MEMIngestionService(db).ingest_precio_bolsa(content, file.filename)
    return summary


@router.post("/gescon/actualizar", response_model=IngestionSummary)
def actualizar_gescon(
    updates: list[GesconEstadoUpdate],
    db: Session = Depends(get_db),
    _: Usuario = Depends(_require_mem_write),
):
    result = MEMIngestionService(db).update_gescon_statuses([u.model_dump() for u in updates])
    return result


# ── Consulta ─────────────────────────────────────────────────────────────────

@router.get("/asic/{proyecto_id}", response_model=list[MEMDatosASICOut])
def get_asic_data(
    proyecto_id: int,
    fecha_desde: str | None = Query(None),
    fecha_hasta: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(MEMDatosASIC).filter(MEMDatosASIC.proyecto_id == proyecto_id)
    if fecha_desde:
        q = q.filter(MEMDatosASIC.fecha >= fecha_desde)
    if fecha_hasta:
        q = q.filter(MEMDatosASIC.fecha <= fecha_hasta)
    return q.order_by(MEMDatosASIC.fecha, MEMDatosASIC.hora).limit(limit).all()


@router.get("/precios", response_model=list[MEMPrecioBolsaOut])
def get_precios(
    fecha_desde: str | None = Query(None),
    fecha_hasta: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(MEMPrecioBolsa)
    if fecha_desde:
        q = q.filter(MEMPrecioBolsa.fecha >= fecha_desde)
    if fecha_hasta:
        q = q.filter(MEMPrecioBolsa.fecha <= fecha_hasta)
    return q.order_by(MEMPrecioBolsa.fecha, MEMPrecioBolsa.hora).limit(limit).all()


@router.get("/gescon/{proyecto_id}", response_model=list[MEMGesconEstadoOut])
def get_gescon_estados(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    return (
        db.query(MEMGesconEstado)
        .filter(MEMGesconEstado.proyecto_id == proyecto_id)
        .order_by(MEMGesconEstado.fecha_actualizacion.desc())
        .all()
    )
