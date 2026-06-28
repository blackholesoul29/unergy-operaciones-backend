"""Utilidad centralizada para el manejo seguro de archivos subidos/descargados.

Mitiga riesgos comunes de subida de archivos:
  - Path traversal (nombres tipo ``../../etc/passwd``) → nombres en disco UUID
    y validación de rutas con :func:`get_secure_path`.
  - Ejecución remota / tipos peligrosos → validación de ``content_type`` contra
    una lista blanca de MIME.
  - Agotamiento de disco → límite de tamaño leyendo por chunks.

Todas las validaciones lanzan :class:`fastapi.HTTPException` para integrarse
directamente con los endpoints FastAPI.
"""
from __future__ import annotations

import pathlib
import uuid

from fastapi import HTTPException, UploadFile

# Tamaño de chunk para la lectura/escritura por streaming (1 MiB).
_CHUNK_SIZE = 1024 * 1024


def generate_secure_filename(original_filename: str) -> str:
    """Devuelve un nombre de archivo seguro ``{uuid}{ext}``.

    Conserva únicamente la extensión del archivo original; el resto se descarta,
    de modo que cualquier componente de ruta o carácter peligroso del nombre
    provisto por el usuario nunca llega al disco.
    """
    extension = pathlib.Path(original_filename or "").suffix
    return f"{uuid.uuid4().hex}{extension}"


async def validate_and_save_file(
    file: UploadFile,
    destination_folder: pathlib.Path,
    secure_filename: str,
    max_size_bytes: int,
    allowed_mime_types: list[str],
) -> None:
    """Valida y guarda ``file`` en ``destination_folder/secure_filename``.

    Valida tipo MIME y nombre, y escribe por chunks aplicando un límite de
    tamaño. Si el archivo excede ``max_size_bytes`` se elimina la escritura
    parcial y se lanza ``HTTPException(413)``.
    """
    if not file.filename:
        raise HTTPException(400, "No se recibió ningún archivo")

    if file.content_type not in allowed_mime_types:
        raise HTTPException(400, "Tipo de archivo no permitido. Use PDF, JPG, PNG o XLSX.")

    destination_folder.mkdir(parents=True, exist_ok=True)
    destination_path = destination_folder / secure_filename

    total = 0
    try:
        with open(destination_path, "wb") as buffer:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size_bytes:
                    raise HTTPException(
                        413,
                        f"El archivo supera el límite de {max_size_bytes // (1024 * 1024)} MB",
                    )
                buffer.write(chunk)
    except BaseException:
        # Limpia la escritura parcial ante cualquier fallo (límite, IO, cancelación).
        destination_path.unlink(missing_ok=True)
        raise


def get_secure_path(base_dir: pathlib.Path, sub_dir: str, filename: str) -> pathlib.Path:
    """Construye y valida una ruta dentro de ``base_dir``.

    Previene path traversal: la ruta resuelta debe quedar contenida dentro de
    ``base_dir`` resuelto. En caso contrario lanza ``HTTPException(400)``.
    """
    candidate = base_dir.joinpath(sub_dir, filename)
    if not candidate.resolve().is_relative_to(base_dir.resolve()):
        raise HTTPException(400, "Ruta de archivo inválida")
    return candidate
