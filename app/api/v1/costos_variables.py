import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, selectinload

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.costos_variables import CostoVariable
from app.models.proyectos import Proyecto
from app.models.servicios import ServicioOperacion
from app.schemas.costos_variables import CostoVariableCreate, CostoVariableUpdate, CostoVariableOut

router = APIRouter(prefix="/costos-variables", tags=["Costos Variables"])

DRIVE_ROOT_FOLDER_ID = "0AD_e3wIWHByDUk9PVA"
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise HTTPException(500, "Google Drive no configurado")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed=false")
    res = service.files().list(
        q=q, fields="files(id)",
        supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return folder["id"]


def _upload_to_drive(file: UploadFile, folder_id: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload
    import io
    content = file.file.read()
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=file.content_type or "application/octet-stream")
    meta = {"name": file.filename, "parents": [folder_id]}
    uploaded = _get_drive_service().files().create(
        body=meta, media_body=media, fields="id",
        supportsAllDrives=True
    ).execute()
    file_id = uploaded["id"]
    _get_drive_service().permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
        supportsAllDrives=True,
    ).execute()
    return f"https://drive.google.com/file/d/{file_id}/view"


def _to_out(c: CostoVariable) -> CostoVariableOut:
    docs = [c.url_factura, c.url_cotizacion, c.url_rut, c.url_certificado_bancario]
    return CostoVariableOut(
        id=c.id,
        proyecto_id=c.proyecto_id,
        proyecto_nombre=c.proyecto.nombre_comercial if c.proyecto else None,
        tipo_accion=c.tipo_accion,
        tipo_equipo=c.tipo_equipo,
        monto=float(c.monto),
        fecha=c.fecha,
        descripcion=c.descripcion,
        observaciones=c.observaciones,
        url_factura=c.url_factura,
        nombre_factura=c.nombre_factura,
        url_cotizacion=c.url_cotizacion,
        nombre_cotizacion=c.nombre_cotizacion,
        url_rut=c.url_rut,
        nombre_rut=c.nombre_rut,
        url_certificado_bancario=c.url_certificado_bancario,
        nombre_certificado_bancario=c.nombre_certificado_bancario,
        documentos_completos=all(d for d in docs),
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ── Proyectos con servicio operación activo ──────────────────────────────────

@router.get("/proyectos-operacion")
def proyectos_con_operacion(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Proyectos que tienen el servicio de operación registrado."""
    rows = (
        db.query(Proyecto)
        .join(ServicioOperacion, ServicioOperacion.proyecto_id == Proyecto.id)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return [{"id": p.id, "nombre_comercial": p.nombre_comercial} for p in rows]


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CostoVariableOut])
def listar(
    proyecto_id: int | None = Query(None),
    tipo_accion: str | None = Query(None),
    tipo_equipo: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        db.query(CostoVariable)
        .options(selectinload(CostoVariable.proyecto))
        .filter(CostoVariable.deleted_at.is_(None))
    )
    if proyecto_id:
        q = q.filter(CostoVariable.proyecto_id == proyecto_id)
    if tipo_accion:
        q = q.filter(CostoVariable.tipo_accion == tipo_accion)
    if tipo_equipo:
        q = q.filter(CostoVariable.tipo_equipo == tipo_equipo)
    costos = q.order_by(CostoVariable.fecha.desc()).all()
    return [_to_out(c) for c in costos]


@router.post("", response_model=CostoVariableOut)
def crear(
    body: CostoVariableCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    costo = CostoVariable(**body.model_dump())
    db.add(costo)
    db.commit()
    db.refresh(costo)
    db.refresh(costo, ["proyecto"])
    return _to_out(costo)


@router.get("/{id}", response_model=CostoVariableOut)
def obtener(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    c = (
        db.query(CostoVariable)
        .options(selectinload(CostoVariable.proyecto))
        .filter(CostoVariable.id == id, CostoVariable.deleted_at.is_(None))
        .first()
    )
    if not c:
        raise HTTPException(404, "Costo no encontrado")
    return _to_out(c)


@router.patch("/{id}", response_model=CostoVariableOut)
def actualizar(
    id: int,
    body: CostoVariableUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    c = db.query(CostoVariable).filter(CostoVariable.id == id, CostoVariable.deleted_at.is_(None)).first()
    if not c:
        raise HTTPException(404, "Costo no encontrado")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(c, field, val)
    db.commit()
    db.refresh(c)
    db.refresh(c, ["proyecto"])
    return _to_out(c)


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    c = db.query(CostoVariable).filter(CostoVariable.id == id, CostoVariable.deleted_at.is_(None)).first()
    if not c:
        raise HTTPException(404, "Costo no encontrado")
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ── Subida de documentos ──────────────────────────────────────────────────────

TIPO_DOC_MAP = {
    "factura": ("url_factura", "nombre_factura"),
    "cotizacion": ("url_cotizacion", "nombre_cotizacion"),
    "rut": ("url_rut", "nombre_rut"),
    "certificado_bancario": ("url_certificado_bancario", "nombre_certificado_bancario"),
}


@router.post("/{id}/documentos/{tipo_doc}", response_model=CostoVariableOut)
async def subir_documento(
    id: int,
    tipo_doc: str,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if tipo_doc not in TIPO_DOC_MAP:
        raise HTTPException(400, f"tipo_doc debe ser uno de: {list(TIPO_DOC_MAP)}")

    c = (
        db.query(CostoVariable)
        .options(selectinload(CostoVariable.proyecto))
        .filter(CostoVariable.id == id, CostoVariable.deleted_at.is_(None))
        .first()
    )
    if not c:
        raise HTTPException(404, "Costo no encontrado")

    content = await archivo.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "Archivo mayor a 20 MB")
    await archivo.seek(0)

    try:
        service = _get_drive_service()
        root = _get_or_create_folder(service, "Costos Variables", DRIVE_ROOT_FOLDER_ID)
        proyecto_folder = _get_or_create_folder(
            service,
            c.proyecto.nombre_comercial if c.proyecto else f"proyecto_{c.proyecto_id}",
            root,
        )
        from googleapiclient.http import MediaIoBaseUpload
        import io
        file_bytes = await archivo.read() if not content else content
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=archivo.content_type or "application/octet-stream")
        meta = {"name": archivo.filename, "parents": [proyecto_folder]}
        uploaded = service.files().create(
            body=meta, media_body=media, fields="id", supportsAllDrives=True
        ).execute()
        file_id = uploaded["id"]
        service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True,
        ).execute()
        url = f"https://drive.google.com/file/d/{file_id}/view"
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error subiendo a Drive: {e}")

    url_field, name_field = TIPO_DOC_MAP[tipo_doc]
    setattr(c, url_field, url)
    setattr(c, name_field, archivo.filename)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.delete("/{id}/documentos/{tipo_doc}", response_model=CostoVariableOut)
def eliminar_documento(
    id: int,
    tipo_doc: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if tipo_doc not in TIPO_DOC_MAP:
        raise HTTPException(400, f"tipo_doc debe ser uno de: {list(TIPO_DOC_MAP)}")
    c = (
        db.query(CostoVariable)
        .options(selectinload(CostoVariable.proyecto))
        .filter(CostoVariable.id == id, CostoVariable.deleted_at.is_(None))
        .first()
    )
    if not c:
        raise HTTPException(404, "Costo no encontrado")
    url_field, name_field = TIPO_DOC_MAP[tipo_doc]
    setattr(c, url_field, None)
    setattr(c, name_field, None)
    db.commit()
    db.refresh(c)
    return _to_out(c)
