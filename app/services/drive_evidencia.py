"""Subida de evidencia (fotos/documentos) a Google Drive vía Service Account.

Mismo patrón ya usado en `app/api/v1/fallas.py` y `app/api/v1/costos_variables.py`
(mismo `DRIVE_ROOT_FOLDER_ID`, mismo formato de objeto adjunto). Se extrae aquí
para no triplicar el boilerplate de Drive al agregar evidencia en Inicio de
Operación; los otros dos módulos no se tocan.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
DRIVE_ROOT_FOLDER_ID = "0AD_e3wIWHByDUk9PVA"


def get_drive_service():
    import json, os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise HTTPException(500, "Google Drive no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON)")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_folder(service, name: str, parent_id: str) -> str:
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


async def subir_archivo(archivo: UploadFile, carpetas: list[str]) -> dict:
    """Sube `archivo` a Drive bajo `Inicio de Operación / carpetas[0] / carpetas[1] / ...`
    y devuelve el objeto adjunto `{id, nombre, url, tamaño, tipo_mime, created_at}`."""
    from googleapiclient.http import MediaIoBaseUpload

    contenido = await archivo.read()
    tamaño = len(contenido)
    if tamaño > MAX_FILE_SIZE:
        raise HTTPException(400, "El archivo supera el límite de 20 MB")

    try:
        service = get_drive_service()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error iniciando Drive: {e}")

    try:
        parent_id = get_or_create_folder(service, "Inicio de Operación", DRIVE_ROOT_FOLDER_ID)
        for nombre_carpeta in carpetas:
            parent_id = get_or_create_folder(service, nombre_carpeta, parent_id)
    except Exception as e:
        raise HTTPException(500, f"Error accediendo carpeta Drive: {e}")

    nombre_original = archivo.filename or f"archivo_{uuid.uuid4().hex}"
    tipo_mime = archivo.content_type or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=tipo_mime)
    file_meta = {"name": nombre_original, "parents": [parent_id]}
    try:
        uploaded = service.files().create(
            body=file_meta, media_body=media, fields="id, webViewLink",
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        raise HTTPException(500, f"Error subiendo archivo a Drive: {e}")

    file_id = uploaded["id"]
    view_url = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    return {
        "id": file_id,
        "nombre": nombre_original,
        "url": view_url,
        "tamaño": tamaño,
        "tipo_mime": tipo_mime,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def eliminar_archivo(archivo_id: str) -> None:
    """Best-effort: si falla el borrado en Drive, no interrumpe el flujo."""
    try:
        service = get_drive_service()
        service.files().delete(fileId=archivo_id, supportsAllDrives=True).execute()
    except Exception:
        pass
