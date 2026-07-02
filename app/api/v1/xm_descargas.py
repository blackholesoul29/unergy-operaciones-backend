import io
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.auth import get_current_user
from app.schemas.xm_descargas import XMDescargaRequest, XMJobResponse, XMJobStatus
from app.services.xm import jobs, tipos
from app.services.xm.orquestador import ejecutar_job

router = APIRouter(prefix="/xm", tags=["Descarga XM"])

EXTENSIONES_VALIDAS = {"txf", "txr", "tx1", "tx2", "tx3", "tx4", "tx5", "tx6", "tx7", "tx8"}


@router.post("/descargas", response_model=XMJobResponse)
def iniciar_descarga(body: XMDescargaRequest, _=Depends(get_current_user)):
    if body.tipo not in tipos.TIPOS_CONFIG:
        raise HTTPException(400, f"Tipo de archivo no soportado: {body.tipo}")
    if body.extension.lower() not in EXTENSIONES_VALIDAS:
        raise HTTPException(400, f"Extensión no soportada: {body.extension}")
    if body.fecha_fin < body.fecha_inicio:
        raise HTTPException(400, "fecha_fin no puede ser anterior a fecha_inicio")

    job_id = jobs.crear_job()
    ftp_params = {"host": body.ftp_host, "usuario": body.ftp_usuario, "clave": body.ftp_clave}

    hilo = threading.Thread(
        target=ejecutar_job,
        args=(job_id, ftp_params, body.tipo, body.extension, body.fecha_inicio, body.fecha_fin, body.enriquecer),
        daemon=True,
    )
    hilo.start()
    return XMJobResponse(job_id=job_id)


@router.get("/descargas/{job_id}", response_model=XMJobStatus)
def estado_descarga(job_id: str, _=Depends(get_current_user)):
    job = jobs.obtener_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado o expirado")
    campos = {k: v for k, v in job.items() if k not in ("resultado", "creado_en")}
    return XMJobStatus(job_id=job_id, **campos)


@router.get("/descargas/{job_id}/archivo")
def descargar_archivo(job_id: str, formato: str = "xlsx", _=Depends(get_current_user)):
    job = jobs.obtener_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado o expirado")
    if job["estado"] != "listo":
        raise HTTPException(409, f"El job aún no está listo (estado actual: {job['estado']})")

    resultado = job["resultado"]
    if formato == "xlsx":
        contenido, nombre = resultado["bytes_xlsx"], resultado["nombre_xlsx"]
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif formato == "txt":
        contenido, nombre = resultado["bytes_txt"], resultado["nombre_txt"]
        media_type = "text/plain"
    else:
        raise HTTPException(400, "formato debe ser 'xlsx' o 'txt'")

    return StreamingResponse(
        io.BytesIO(contenido), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
