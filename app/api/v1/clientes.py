import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente, ClienteServicio, ClienteDocumentoComercial
from app.schemas.clientes import (
    ClienteCreate, ClienteUpdate, ClienteOut,
    ClienteServicioCreate, ClienteServicioOut,
    ClienteDocumentoCreate, ClienteDocumentoUpdate, ClienteDocumentoOut,
)
from app.schemas.common import PaginatedResponse

UPLOADS_DIR = Path("uploads/clientes")
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

router = APIRouter(prefix="/clientes", tags=["Clientes"])


def _get_cliente_or_404(id: int, db: Session) -> Cliente:
    c = db.query(Cliente).options(
        selectinload(Cliente.servicios),
        selectinload(Cliente.documentos_comerciales),
    ).filter(Cliente.id == id).first()
    if not c:
        raise HTTPException(404, "Cliente no encontrado")
    return c


@router.get("", response_model=PaginatedResponse[ClienteOut])
def list_clientes(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    # Ignore: todo delete
    print("force deploy trick")
    query = db.query(Cliente)
    if q:
        query = query.filter(Cliente.razon_social_nombre.ilike(f"%{q}%"))
    total = query.count()
    items = query.order_by(Cliente.razon_social_nombre).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.post("", response_model=ClienteOut, status_code=201)
def create_cliente(data: ClienteCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cliente = Cliente(**data.model_dump())
    db.add(cliente)
    db.commit()
    return _get_cliente_or_404(cliente.id, db)


@router.get("/{id}", response_model=ClienteOut)
def get_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_cliente_or_404(id, db)


@router.patch("/{id}", response_model=ClienteOut)
def update_cliente(id: int, data: ClienteUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cliente = _get_cliente_or_404(id, db)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(cliente, k, v)
    db.commit()
    return _get_cliente_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")
    db.delete(cliente)
    db.commit()


# ── Servicios ────────────────────────────────────────────────────────────────

@router.get("/{id}/servicios", response_model=list[ClienteServicioOut])
def list_servicios(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return db.query(ClienteServicio).filter(ClienteServicio.cliente_id == id).all()


@router.post("/{id}/servicios", response_model=ClienteServicioOut, status_code=201)
def add_servicio(id: int, data: ClienteServicioCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    existing = db.query(ClienteServicio).filter_by(cliente_id=id, tipo=data.tipo).first()
    if existing:
        raise HTTPException(400, f"El cliente ya tiene el servicio '{data.tipo}' registrado")
    s = ClienteServicio(cliente_id=id, **data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{id}/servicios/{servicio_id}", status_code=204)
def remove_servicio(id: int, servicio_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(ClienteServicio).filter_by(id=servicio_id, cliente_id=id).first()
    if not s:
        raise HTTPException(404, "Servicio no encontrado")
    db.delete(s)
    db.commit()


# ── Documentos comerciales (ofertas / contratos) ──────────────────────────────

@router.get("/{id}/documentos", response_model=list[ClienteDocumentoOut])
def list_documentos(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return (
        db.query(ClienteDocumentoComercial)
        .filter(ClienteDocumentoComercial.cliente_id == id)
        .order_by(ClienteDocumentoComercial.tipo, ClienteDocumentoComercial.fecha)
        .all()
    )


@router.post("/{id}/documentos", response_model=ClienteDocumentoOut, status_code=201)
def add_documento(id: int, data: ClienteDocumentoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    doc = ClienteDocumentoComercial(cliente_id=id, **data.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{id}/documentos/{doc_id}", response_model=ClienteDocumentoOut)
def update_documento(id: int, doc_id: int, data: ClienteDocumentoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(doc, k, v)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{id}/documentos/{doc_id}", status_code=204)
def delete_documento(id: int, doc_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    # Borrar archivo físico si existe
    if doc.archivo_url and doc.archivo_url.startswith("/static/uploads/"):
        ruta = Path(doc.archivo_url.lstrip("/").replace("static/", "", 1))
        if ruta.exists():
            ruta.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


@router.post("/{id}/documentos/{doc_id}/archivo", response_model=ClienteDocumentoOut)
async def upload_archivo_documento(
    id: int,
    doc_id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")

    if archivo.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"Tipo de archivo no permitido. Use PDF, JPG o PNG.")

    contenido = await archivo.read()
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(400, "El archivo supera el límite de 20 MB")

    # Borrar archivo anterior si existe
    if doc.archivo_url and doc.archivo_url.startswith("/static/uploads/"):
        ruta_ant = Path(doc.archivo_url.lstrip("/").replace("static/", "", 1))
        ruta_ant.unlink(missing_ok=True)

    # Guardar nuevo archivo
    ext = Path(archivo.filename).suffix.lower() if archivo.filename else ".pdf"
    nombre_guardado = f"{uuid.uuid4().hex}{ext}"
    carpeta = UPLOADS_DIR / str(id)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_nueva = carpeta / nombre_guardado
    ruta_nueva.write_bytes(contenido)

    doc.archivo_url = f"/static/uploads/clientes/{id}/{nombre_guardado}"
    doc.archivo_nombre = archivo.filename or nombre_guardado
    db.commit()
    db.refresh(doc)
    return doc
