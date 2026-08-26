"""Ingesta de archivos de XM: hash, validación y metadatos.

La idempotencia es por `sha256` del contenido, no por nombre: los mismos CSV llegan
con nombres distintos en distintos zips, y los `_V2` tienen el mismo nombre con
contenido diferente.
"""
from __future__ import annotations

import datetime
import hashlib
import re

from app.services.garantias_modelo.normalizar import version_de_nombre
from app.services.garantias_modelo.validacion import validar_estructura

_RE_DIARIO = re.compile(r"^([A-Za-z]+)(\d{2})(\d{2})\.", re.IGNORECASE)

# Tipos de insumo que este plan ingiere. Un nombre que no matchee queda marcado como
# esquema inválido en vez de entrar sin tipo.
_TIPOS = {"balcttos", "trsd", "dspcttos", "arrpas"}


def sha256_de(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def tipo_de_nombre(nombre: str) -> str | None:
    m = _RE_DIARIO.match(nombre)
    if not m:
        return None
    t = m.group(1).lower()
    return t if t in _TIPOS else None


def preparar_archivo(nombre: str, contenido: bytes,
                     *, disponible_desde: datetime.datetime | None,
                     anio: int | None = None) -> dict:
    """Metadatos listos para `xm_archivo`. No escribe nada.

    `disponible_desde` es obligatorio en la práctica: quien llama tiene que
    indicarlo siempre — observado, para una descarga en vivo, o calculado por quien
    llama a partir de la regla de publicación de XM, para un backfill histórico.
    Esta función **no lo adivina**: los zips del corpus no conservan la fecha de
    publicación (todas las entradas traen la fecha de descarga), así que no hay
    forma de derivarlo de los datos. Errar el filtro anti-leakage en cualquier
    dirección — de más o de menos — es peor que rechazar el archivo, así que si se
    pasa `None` el archivo vuelve marcado como no ingerible (`esquema_ok=False`) en
    vez de estampar `now()`.
    """
    tipo = tipo_de_nombre(nombre)
    version = version_de_nombre(nombre)

    if disponible_desde is None:
        ok = False
        detalle = {
            "motivo": (
                "disponible_desde desconocido: la fecha de disponibilidad no vino "
                "de quien llama y esta función no la adivina. Hay que indicarla "
                "explícitamente (observada, o calculada por quien llama a partir "
                "de la regla de publicación de XM para un backfill)."
            )
        }
    else:
        ok, detalle = validar_estructura(contenido, tipo) if tipo else (False, {
            "motivo": f"tipo no reconocido en el nombre: {nombre}"})

    fecha = None
    m = _RE_DIARIO.match(nombre)
    if m and anio:
        try:
            fecha = datetime.date(anio, int(m.group(2)), int(m.group(3)))
        except ValueError:
            fecha = None

    return {
        "tipo": tipo or "desconocido",
        "nombre_archivo": nombre[:300],
        "version": version,
        "periodo_ini": fecha,
        "periodo_fin": fecha,
        "disponible_desde": disponible_desde,
        "origen_disponibilidad": "observado" if disponible_desde is not None else None,
        "sha256": sha256_de(contenido),
        "bytes_len": len(contenido),
        "esquema_ok": ok,
        "esquema_detalle": None if ok else detalle,
    }
