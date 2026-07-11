"""API del pipeline de datos XM: carga manual y consulta de datos ingeridos.

Endpoints (montados bajo /api/v1/xm-data):
  * POST /upload  — sube un Excel (`listado_recursos` / `generacion_distribuida`)
                    y lo procesa con el servicio de ingesta.
  * GET  /        — listado paginado con filtros por fecha y código de recurso.
  * GET  /status  — metadatos de la última ingesta.
"""
import os
import tempfile
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.crud import crud_liquidacion_xm
from app.models.usuarios import Usuario
from app.schemas.liquidacion_xm import (
    IngestionResumen, IngestionStatus, LiquidacionXMDatoPage,
)
from app.services import xm_ingestion_service

router = APIRouter(prefix="/xm-data", tags=["Datos XM"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _require_xm_write(current: Usuario = Depends(get_current_user)) -> Usuario:
    if current.rol.value not in ("admin", "liquidaciones"):
        raise HTTPException(403, "Se requiere rol admin o liquidaciones")
    return current


@router.post("/upload", response_model=IngestionResumen)
async def upload_xm_file(
    file: UploadFile = File(...),
    file_type: Optional[str] = Form(None),
    fecha_default: Optional[date] = Form(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(_require_xm_write),
):
    """Sube y procesa un archivo Excel de XM.

    `file_type` es opcional: si se omite, se infiere del nombre del archivo.
    `fecha_default` se usa como fecha de las filas que no traen columna de fecha
    (p. ej. listado_recursos).
    """
    contenido = await file.read()
    if not contenido:
        raise HTTPException(400, "Archivo vacío")
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(413, "Archivo demasiado grande (máx. 50 MB)")

    nombre = file.filename or "archivo.xlsx"
    if not nombre.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Solo se aceptan archivos Excel (.xlsx / .xls)")

    suffix = os.path.splitext(nombre)[1] or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(contenido)
        tmp.close()
        try:
            resumen = xm_ingestion_service.process_xm_file(
                db, tmp.name, file_type,
                fuente_archivo=nombre, fecha_default=fecha_default,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return resumen


@router.get("", response_model=LiquidacionXMDatoPage)
@router.get("/", response_model=LiquidacionXMDatoPage, include_in_schema=False)
def listar_xm_data(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    codigo_recurso: Optional[str] = Query(None),
    fuente_archivo: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Listado paginado de datos XM ingeridos, con filtros opcionales."""
    items, total = crud_liquidacion_xm.get_filtered(
        db,
        start_date=start_date,
        end_date=end_date,
        codigo_recurso=codigo_recurso,
        fuente_archivo=fuente_archivo,
        skip=skip,
        limit=limit,
    )
    return {"total": total, "skip": skip, "limit": limit, "items": items}


@router.get("/status", response_model=IngestionStatus)
def estado_ingesta(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Metadatos de la última ingesta: timestamp, archivo y total de registros."""
    return crud_liquidacion_xm.get_status(db)
