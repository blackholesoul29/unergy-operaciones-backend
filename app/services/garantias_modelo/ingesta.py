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

    `disponible_desde=None` significa backfill histórico: no hay timestamp real de
    descarga, así que la disponibilidad queda marcada como derivada. Toda consulta
    anti-leakage pasa por el mismo campo, y la derivación queda auditable.
    """
    tipo = tipo_de_nombre(nombre)
    version = version_de_nombre(nombre)

    ok, detalle = validar_estructura(contenido, tipo) if tipo else (False, {
        "motivo": f"tipo no reconocido en el nombre: {nombre}"})

    fecha = None
    m = _RE_DIARIO.match(nombre)
    if m and anio:
        try:
            fecha = datetime.date(anio, int(m.group(2)), int(m.group(3)))
        except ValueError:
            fecha = None

    observado = disponible_desde is not None
    return {
        "tipo": tipo or "desconocido",
        "nombre_archivo": nombre[:300],
        "version": version,
        "periodo_ini": fecha,
        "periodo_fin": fecha,
        "disponible_desde": disponible_desde or datetime.datetime.now(datetime.timezone.utc),
        "origen_disponibilidad": "observado" if observado else "derivado",
        "sha256": sha256_de(contenido),
        "bytes_len": len(contenido),
        "esquema_ok": ok,
        "esquema_detalle": None if ok else detalle,
    }
