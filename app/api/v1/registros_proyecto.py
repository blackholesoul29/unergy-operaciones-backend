"""Endpoints de la seccion "Registros": expediente documental por proyecto.

Rutas (bajo /api/v1/registros-proyecto):

  GET    /catalogos                                  items y parametros de los dos procesos
  GET    /{proyecto_id}                              timeline completo del expediente
  GET    /{proyecto_id}/parametros                   todos los valores del proyecto
  PUT    /{proyecto_id}/parametros                   guardar valores (crea o actualiza)
  GET    /{proyecto_id}/{proceso}/{item_codigo}      formulario de un item
  PATCH  /{proyecto_id}/{proceso}/{item_codigo}      datos de la casilla (radicado, estado...)
  POST   /{proyecto_id}/{proceso}/{item_codigo}/archivos          montar por link
  POST   /{proyecto_id}/{proceso}/{item_codigo}/archivos/subir    subir a Drive
  DELETE /archivos/{archivo_id}                      quitar un archivo
  DELETE /parametros/{parametro_id}                  borrar un valor
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.registros_proyecto import (
    ArchivoDocumentoProyecto, DocumentoProyecto, OrigenArchivo, ParametroProyecto,
)
from app.models.usuarios import Usuario
from app.schemas.registros_proyecto import (
    ArchivoCreate, ArchivoOut, DocumentoOut, DocumentoUpdate, FormularioItemOut,
    ParametroOut, ParametrosGuardar, ResumenProyectoOut,
)
from app.services.registros_proyecto import service

router = APIRouter(prefix="/registros-proyecto", tags=["Registros - expediente"])


def _check_operaciones(current: Usuario) -> None:
    if current.rol.value not in ("admin", "operaciones"):
        raise HTTPException(status_code=403, detail="Requiere rol operaciones o admin")


def _doc(db: Session, proyecto_id: int, proceso: str, item_codigo: str) -> DocumentoProyecto:
    try:
        return service.get_or_create_documento(db, proyecto_id, proceso.upper(), item_codigo)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
@router.get("/catalogos")
def obtener_catalogos(_: Usuario = Depends(get_current_user)):
    """Items de los dos procesos y definicion de cada parametro.

    La UI lo pide una vez y con eso dibuja el timeline y todos los formularios.
    """
    return service.catalogos()


@router.get("")
def listar_proyectos(db: Session = Depends(get_db),
                     _: Usuario = Depends(get_current_user)):
    """Indice de la seccion: todos los proyectos con el avance de cada proceso."""
    return service.listar_proyectos(db)


@router.get("/{proyecto_id}", response_model=ResumenProyectoOut)
def resumen(proyecto_id: int, proceso: str | None = None,
            db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    try:
        return service.resumen_proyecto(db, proyecto_id, proceso.upper() if proceso else None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
@router.get("/{proyecto_id}/parametros", response_model=list[ParametroOut])
def listar_parametros(proyecto_id: int, db: Session = Depends(get_db),
                      _: Usuario = Depends(get_current_user)):
    return service.listar_parametros(db, proyecto_id)


@router.put("/{proyecto_id}/parametros", response_model=list[ParametroOut])
def guardar_parametros(proyecto_id: int, data: ParametrosGuardar,
                       db: Session = Depends(get_db),
                       current: Usuario = Depends(get_current_user)):
    """Guarda valores. Si el dato ya existe se actualiza: nunca se duplica."""
    _check_operaciones(current)
    try:
        return service.guardar_parametros(
            db, proyecto_id,
            [v.model_dump(exclude_unset=True) for v in data.valores],
            actor=current.nombre,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/parametros/{parametro_id}", status_code=204)
def eliminar_parametro(parametro_id: int, db: Session = Depends(get_db),
                       current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    fila = db.get(ParametroProyecto, parametro_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Parametro no encontrado")
    service.eliminar_parametro(db, fila)


# ---------------------------------------------------------------------------
# Items del expediente
# ---------------------------------------------------------------------------
@router.get("/{proyecto_id}/{proceso}/{item_codigo}", response_model=FormularioItemOut)
def formulario_item(proyecto_id: int, proceso: str, item_codigo: str,
                    db: Session = Depends(get_db),
                    _: Usuario = Depends(get_current_user)):
    """La casilla, sus archivos y los campos que le corresponden con su valor actual."""
    try:
        return service.formulario_item(db, proyecto_id, proceso.upper(), item_codigo)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{proyecto_id}/{proceso}/{item_codigo}", response_model=DocumentoOut)
def actualizar_documento(proyecto_id: int, proceso: str, item_codigo: str,
                         data: DocumentoUpdate, db: Session = Depends(get_db),
                         current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    doc = _doc(db, proyecto_id, proceso, item_codigo)
    try:
        return service.actualizar_documento(db, doc, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{proyecto_id}/{proceso}/{item_codigo}/archivos",
             response_model=ArchivoOut, status_code=201)
def montar_archivo(proyecto_id: int, proceso: str, item_codigo: str,
                   data: ArchivoCreate, db: Session = Depends(get_db),
                   current: Usuario = Depends(get_current_user)):
    """Monta un archivo por enlace (Drive, SharePoint, el que sea)."""
    _check_operaciones(current)
    doc = _doc(db, proyecto_id, proceso, item_codigo)
    try:
        return service.agregar_archivo(
            db, doc, {**data.model_dump(), "subido_por": current.nombre})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{proyecto_id}/{proceso}/{item_codigo}/archivos/subir",
             response_model=ArchivoOut, status_code=201)
async def subir_archivo(proyecto_id: int, proceso: str, item_codigo: str,
                        archivo: UploadFile = File(...),
                        db: Session = Depends(get_db),
                        current: Usuario = Depends(get_current_user)):
    """Sube el archivo al Drive de la empresa y lo monta en la casilla.

    Reusa el servicio de evidencia que ya usa el resto de la plataforma, para
    que el expediente quede en el mismo Drive y con el mismo arbol de carpetas.
    """
    _check_operaciones(current)
    doc = _doc(db, proyecto_id, proceso, item_codigo)

    from app.models.proyectos import Proyecto
    from app.services.drive_evidencia import subir_archivo as subir_a_drive

    proyecto = db.get(Proyecto, proyecto_id)
    item = service.definicion_item(doc.proceso, doc.item_codigo) or {}
    carpeta_item = f"{doc.item_codigo} {item.get('titulo', '')}".strip()

    try:
        subido = await subir_a_drive(
            archivo, [proyecto.nombre_comercial, "Registros", doc.proceso, carpeta_item])
    except Exception as e:                       # el servicio de Drive es externo
        raise HTTPException(status_code=502, detail=f"No se pudo subir a Drive: {e}")

    try:
        return service.agregar_archivo(db, doc, {
            "origen": OrigenArchivo.DRIVE,
            "url": subido["url"],
            "nombre_archivo": subido.get("nombre") or archivo.filename,
            "drive_file_id": subido.get("id"),
            "tamano_bytes": subido.get("tamaño") or subido.get("tamano"),
            "tipo_mime": subido.get("tipo_mime"),
            "subido_por": current.nombre,
        })
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/archivos/{archivo_id}", status_code=204)
def eliminar_archivo(archivo_id: int, db: Session = Depends(get_db),
                     current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    archivo = db.get(ArchivoDocumentoProyecto, archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    service.eliminar_archivo(db, archivo)
