"""Subida de evidencia (fotos/documentos) a Google Drive por Service Account.

Vive en `apps/comun/` y no en un dominio porque el mismo patrón lo usan hoy
fallas, costos variables y el panel contable, cada uno con su propia copia del
boilerplate. Esta es la versión buena; al portar esos recursos deberían apuntar
acá en vez de duplicarla otra vez.

Diferencias con `app/services/drive_evidencia.py`, del que se portó:

- Es **sincrónico** y recibe un `UploadedFile` de Django, no un `UploadFile` de
  FastAPI (`.read()` allí es una corrutina; acá no).
- Levanta excepciones propias en vez de `HTTPException`: un servicio de dominio
  no conoce HTTP. La vista las traduce.
"""

import io
import json
import os
import uuid
from datetime import datetime, timezone

MAX_TAMANO = 20 * 1024 * 1024
CARPETA_RAIZ = "0AD_e3wIWHByDUk9PVA"
SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveNoConfigurado(RuntimeError):
    pass


class ArchivoDemasiadoGrande(ValueError):
    pass


class DriveFallo(RuntimeError):
    pass


def servicio():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credenciales_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not credenciales_json:
        raise DriveNoConfigurado(
            "Google Drive no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON)"
        )
    credenciales = service_account.Credentials.from_service_account_info(
        json.loads(credenciales_json), scopes=SCOPES
    )
    return build("drive", "v3", credentials=credenciales, cache_discovery=False)


def carpeta(servicio_drive, nombre: str, padre: str) -> str:
    """Id de la carpeta `nombre` dentro de `padre`, creándola si no existe."""
    consulta = (
        f"name='{nombre}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{padre}' in parents and trashed=false"
    )
    respuesta = servicio_drive.files().list(
        q=consulta, fields="files(id)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    existentes = respuesta.get("files", [])
    if existentes:
        return existentes[0]["id"]

    creada = servicio_drive.files().create(
        body={
            "name": nombre,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [padre],
        },
        fields="id", supportsAllDrives=True,
    ).execute()
    return creada["id"]


def subir(archivo, carpetas: list[str]) -> dict:
    """Sube el archivo bajo `Inicio de Operación / carpetas…`.

    Devuelve el adjunto `{id, nombre, url, tamaño, tipo_mime, created_at}`, que
    es la forma que ya guardan los JSONB de evidencia.
    """
    from googleapiclient.http import MediaIoBaseUpload

    contenido = archivo.read()
    tamano = len(contenido)
    if tamano > MAX_TAMANO:
        raise ArchivoDemasiadoGrande("El archivo supera el límite de 20 MB")

    drive = servicio()
    try:
        padre = carpeta(drive, "Inicio de Operación", CARPETA_RAIZ)
        for nombre in carpetas:
            padre = carpeta(drive, nombre, padre)
    except Exception as exc:
        raise DriveFallo(f"Error accediendo carpeta Drive: {exc}") from exc

    nombre_original = getattr(archivo, "name", None) or f"archivo_{uuid.uuid4().hex}"
    tipo_mime = getattr(archivo, "content_type", None) or "application/octet-stream"
    try:
        subido = drive.files().create(
            body={"name": nombre_original, "parents": [padre]},
            media_body=MediaIoBaseUpload(io.BytesIO(contenido), mimetype=tipo_mime),
            fields="id, webViewLink", supportsAllDrives=True,
        ).execute()
    except Exception as exc:
        raise DriveFallo(f"Error subiendo archivo a Drive: {exc}") from exc

    file_id = subido["id"]
    return {
        "id": file_id,
        "nombre": nombre_original,
        "url": subido.get(
            "webViewLink", f"https://drive.google.com/file/d/{file_id}/view"
        ),
        "tamaño": tamano,
        "tipo_mime": tipo_mime,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def eliminar(archivo_id: str) -> None:
    """Borrado «lo mejor que se pueda»: si falla en Drive, no corta el flujo.

    Dejar un archivo huérfano en Drive es preferible a no poder quitar la
    evidencia de la ficha.
    """
    try:
        servicio().files().delete(
            fileId=archivo_id, supportsAllDrives=True
        ).execute()
    except Exception:
        pass
