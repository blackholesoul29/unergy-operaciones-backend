"""Validadores Pydantic estrictos para columnas JSONB.

Centraliza la validación del contenido almacenado en columnas JSONB que hoy
aceptan estructura libre:

  - ``fallas.fotos_urls``            → lista de adjuntos (ver ``FotoUrlSchema``)
  - ``gestion_registros.archivos_json`` → lista de adjuntos (ver ``ArchivoJsonSchema``)

Notas de diseño (importantes):

``fotos_urls`` es **polimórfico** en producción. Cada elemento de la lista puede
ser:

  1. Un objeto/dict con campos completos, como lo genera el endpoint de subida a
     Drive (``/fallas/{id}/archivos``)::

         {"id": "...", "nombre": "foto.jpg", "url": "https://...",
          "tamaño": 12345, "tipo_mime": "image/jpeg", "created_at": "..."}

  2. Una cadena legada con la URL, opcionalmente con sufijo ``#nombre``::

         "https://drive.google.com/file/d/XYZ/view#foto.jpg"

  3. Una cadena de URL simple (p. ej. las ``driveUrls`` enviadas desde
     monitoreo).

Por eso NO se exige ``list[str]`` de URLs puras: eso rompería los adjuntos en
formato objeto y el formato legado. La validación acepta ambas formas y solo
garantiza que la URL sea http/https y que la estructura básica sea correcta.

Las funciones ``validate_fotos_urls`` y ``validate_archivos_json`` lanzan
``ValueError`` con un mensaje claro indicando qué elemento/campo falló, para que
la capa de API lo traduzca a un ``400 Bad Request`` legible.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, field_validator


def _validar_url_http(valor: str, *, campo: str = "url") -> str:
    """Valida que ``valor`` sea una URL http/https no vacía."""
    if not isinstance(valor, str):
        raise ValueError(f"{campo} debe ser una cadena de texto")
    url = valor.strip()
    if not url:
        raise ValueError(f"{campo} no puede estar vacío")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"URL inválida en {campo}: '{valor}' (se espera http:// o https://)")
    # Debe tener algo después del esquema
    resto = url.split("://", 1)[1].strip()
    if not resto:
        raise ValueError(f"URL inválida en {campo}: '{valor}'")
    return valor


class FotoUrlSchema(BaseModel):
    """Adjunto de una falla en formato objeto (el que genera la subida a Drive).

    Permite campos extra para no perder metadata histórica, pero exige una
    ``url`` http/https válida.
    """

    url: str
    id: Optional[str] = None
    nombre: Optional[str] = None
    # Nombre real de la columna usada en el código: "tamaño" (con ñ).
    tamaño: Optional[int] = None
    tipo_mime: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("url")
    @classmethod
    def _validar_url(cls, v: str) -> str:
        return _validar_url_http(v, campo="url")


class ArchivoJsonSchema(BaseModel):
    """Adjunto de un registro de gestión (``gestion_registros.archivos_json``).

    Mantiene la misma forma que los adjuntos de fallas (es la funcionalidad
    hermana): cada archivo es un objeto con ``nombre`` y ``url`` http/https,
    más metadata opcional. Se admiten campos extra.
    """

    nombre: str
    url: str
    tipo_mime: Optional[str] = None
    tamaño: Optional[int] = None
    created_at: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator("nombre")
    @classmethod
    def _validar_nombre(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("falta el campo requerido 'nombre' en archivos_json")
        return v

    @field_validator("url")
    @classmethod
    def _validar_url(cls, v: str) -> str:
        return _validar_url_http(v, campo="url")


def _validar_item_foto(item: Any, idx: int) -> None:
    """Valida un único elemento de ``fotos_urls`` (objeto o cadena legada)."""
    if isinstance(item, dict):
        try:
            FotoUrlSchema.model_validate(item)
        except Exception as e:  # pydantic.ValidationError u otro
            raise ValueError(f"fotos_urls[{idx}]: {_primer_error(e)}") from None
        return
    if isinstance(item, str):
        # Formato legado: "url#nombre" o solo "url".
        url_part = item.rsplit("#", 1)[0] if "#" in item else item
        try:
            _validar_url_http(url_part, campo=f"fotos_urls[{idx}]")
        except ValueError as e:
            raise ValueError(str(e)) from None
        return
    raise ValueError(
        f"fotos_urls[{idx}]: cada elemento debe ser un objeto de adjunto o una URL, "
        f"se recibió {type(item).__name__}"
    )


def validate_fotos_urls(value: Any) -> Any:
    """Valida el contenido de ``fallas.fotos_urls``.

    Acepta ``None`` (sin fotos) o una lista de adjuntos (objetos o cadenas de
    URL). Devuelve el valor sin modificar para no alterar el almacenamiento.
    Lanza ``ValueError`` con un mensaje claro si algo no cumple.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("fotos_urls debe ser una lista de adjuntos")
    for idx, item in enumerate(value):
        _validar_item_foto(item, idx)
    return value


def validate_archivos_json(value: Any) -> Any:
    """Valida el contenido de ``gestion_registros.archivos_json``.

    Acepta ``None`` o una lista de objetos de adjunto (``ArchivoJsonSchema``).
    Devuelve el valor sin modificar. Lanza ``ValueError`` si algo no cumple.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("archivos_json debe ser una lista de adjuntos")
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(
                f"archivos_json[{idx}]: cada elemento debe ser un objeto, "
                f"se recibió {type(item).__name__}"
            )
        try:
            ArchivoJsonSchema.model_validate(item)
        except Exception as e:
            raise ValueError(f"archivos_json[{idx}]: {_primer_error(e)}") from None
    return value


def _primer_error(exc: Exception) -> str:
    """Extrae un mensaje legible del primer error de una ValidationError."""
    errs = getattr(exc, "errors", None)
    if callable(errs):
        try:
            detalles = errs()
            if detalles:
                primero = detalles[0]
                loc = ".".join(str(p) for p in primero.get("loc", ()))
                msg = primero.get("msg", "valor inválido")
                return f"{loc}: {msg}" if loc else msg
        except Exception:
            pass
    return str(exc)


__all__ = [
    "FotoUrlSchema",
    "ArchivoJsonSchema",
    "validate_fotos_urls",
    "validate_archivos_json",
]
