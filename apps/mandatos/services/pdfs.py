"""Los PDF firmados de los mandatos: dónde viven y cómo se sirven.

Llegan por dos caminos y hay que servir los dos: sueltos por «Subir firmados»,
o dentro del ZIP del período.
"""

import io
import zipfile
from pathlib import Path

from django.conf import settings

MAX_PDF = 20 * 1024 * 1024
MAX_ZIP = 100 * 1024 * 1024


class NombreInvalido(ValueError):
    pass


class SinPdf(LookupError):
    pass


def directorio_pdf() -> Path:
    ruta = Path(settings.BASE_DIR) / "uploads" / "mandatos"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def directorio_zip() -> Path:
    ruta = directorio_pdf() / "zips"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _dentro_de(ruta: Path, carpeta: Path) -> bool:
    try:
        ruta.resolve().relative_to(carpeta.resolve())
    except ValueError:
        return False
    return True


def guardar_pdf(nombre: str, contenido: bytes) -> Path:
    destino = directorio_pdf() / Path(nombre).name
    destino.write_bytes(contenido)
    return destino


def ruta_de_nombre(nombre: str) -> Path:
    """La ruta de un PDF ya subido, a partir de SOLO su nombre de archivo.

    Se recibe el nombre y nunca una ruta, y además se comprueba que quede
    dentro del directorio: si no, el cliente podría asociar a un mandato
    cualquier archivo del servidor.
    """
    destino = directorio_pdf() / Path(nombre).name
    if not _dentro_de(destino, directorio_pdf()):
        raise NombreInvalido("Nombre de archivo inválido.")
    if not destino.is_file():
        raise SinPdf(
            "El archivo no existe en el servidor. Súbelo primero con "
            "'Subir firmados'."
        )
    return destino


def contenido_del_mandato(mandato) -> tuple[bytes, str]:
    """`(bytes, nombre)` del PDF firmado, venga suelto o dentro del ZIP."""
    if mandato.pdf_firmado_ruta:
        ruta = Path(mandato.pdf_firmado_ruta)
        if not _dentro_de(ruta, directorio_pdf()):
            raise SinPdf("PDF no disponible.")
        if not ruta.is_file():
            raise SinPdf("El archivo del PDF ya no existe en el servidor.")
        return ruta.read_bytes(), (mandato.pdf_firmado_nombre or ruta.name)

    if mandato.archivo_zip_nombre:
        periodo = mandato.periodo.strftime("%Y-%m")
        zip_path = directorio_zip() / f"{periodo}.zip"
        if not zip_path.exists():
            raise SinPdf("No se encontró el ZIP del período.")
        with zipfile.ZipFile(zip_path) as archivo:
            entrada = next(
                (
                    n for n in archivo.namelist()
                    if n.split("/")[-1] == mandato.archivo_zip_nombre
                ),
                None,
            )
            if entrada is None:
                raise SinPdf("El PDF no está dentro del ZIP del período.")
            return archivo.read(entrada), mandato.archivo_zip_nombre

    raise SinPdf("Este mandato no tiene PDF asociado.")


def pdfs_del_zip(contenido: bytes) -> list[str]:
    """Los nombres de PDF dentro del ZIP, sin las carpetas."""
    try:
        archivo = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo no es un ZIP válido.") from exc
    return [
        n for n in archivo.namelist()
        if n.lower().endswith(".pdf") and not n.endswith("/")
    ]


def guardar_zip(periodo: str, contenido: bytes) -> None:
    (directorio_zip() / f"{periodo}.zip").write_bytes(contenido)
