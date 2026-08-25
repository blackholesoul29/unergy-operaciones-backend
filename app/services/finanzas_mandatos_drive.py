"""Subida de PDFs de mandatos a Google Drive (patron de fallas.py)."""
from __future__ import annotations
import io
import json
import os
from fastapi import HTTPException

# Carpeta raiz en el shared drive donde se guardan los mandatos. Override por env.
DRIVE_MANDATOS_FOLDER_ID = os.environ.get(
    "DRIVE_MANDATOS_FOLDER_ID", "0AD_e3wIWHByDUk9PVA")


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise HTTPException(500, "Google Drive no configurado (GOOGLE_SERVICE_ACCOUNT_JSON)")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder(service, name: str, parent_id: str) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed=false")
    res = service.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]}
    return service.files().create(body=meta, fields="id",
                                  supportsAllDrives=True).execute()["id"]


def subir_pdf(contenido: bytes, nombre: str, subcarpeta: str) -> dict:
    """Sube el PDF a DRIVE_MANDATOS_FOLDER_ID/subcarpeta. Devuelve {id, url}."""
    from googleapiclient.http import MediaIoBaseUpload
    service = _service()
    folder_id = _folder(service, subcarpeta, DRIVE_MANDATOS_FOLDER_ID)
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype="application/pdf")
    up = service.files().create(
        body={"name": nombre, "parents": [folder_id]},
        media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
    fid = up["id"]
    return {"id": fid, "url": up.get("webViewLink", f"https://drive.google.com/file/d/{fid}/view")}
