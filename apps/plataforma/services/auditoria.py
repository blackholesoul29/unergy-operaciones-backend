"""Constancia de los borrados que el ORM no ve.

Puerto de la parte de `app/services/audit.py` que hace falta acá:
`registrar_borrado`. Los borrados masivos (`DELETE FROM x WHERE …`) y los
`UPDATE` en bloque no pasan por las señales de modelo, así que nadie los
registra. Los dos endpoints de fusión de duplicados borran así, y hasta el
2026-08-27 **borrar una planta no dejaba ni una fila en `audit_log`**: la
operación más destructiva de la app era la única sin rastro.

Guarda el **snapshot completo de la fila** antes de que desaparezca — que es
justo lo que una señal genérica no puede dar: esa ve la sentencia, no el
contenido.

⚠️ **Hay que llamarla ANTES de tocar la fila.** Los merges vacían campos del
perdedor antes de darlo de baja; llamarla al final guardaría una foto mutilada.

El `SELECT *` es deliberado: enumerar columnas a mano queda viejo en días y
además funciona en cualquier dialecto, que `row_to_json` no.

`audit_log` es una de las 28 tablas sin modelo (ver apps/README.md); por eso el
INSERT va en SQL crudo y no por el ORM.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import connection

# `registrar_borrado` interpola el nombre de tabla en el SQL, así que no puede
# aceptar cualquier cosa aunque hoy solo la llamen con literales.
_NOMBRE_TABLA = re.compile(r"^[a-z_][a-z0-9_]*$")


def _serializar(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, dict)):
        return v
    return str(v)


def registrar_borrado(tabla: str, registro_id: int, *, usuario=None,
                      contexto: dict | None = None, tipo: str = "hard") -> bool:
    """Retrata la fila y deja el registro en `audit_log`.

    Devuelve False si la fila no existe: no hay nada que retratar.

    `usuario` se pasa explícito (en FastAPI viajaba en `session.info`, que no
    tiene equivalente acá): normalmente `request.user`.
    """
    if not _NOMBRE_TABLA.match(tabla):
        raise ValueError(f"nombre de tabla no valido: {tabla!r}")

    with connection.cursor() as cur:
        cur.execute(f"SELECT * FROM {tabla} WHERE id = %s", [registro_id])
        columnas = [c[0] for c in cur.description]
        fila = cur.fetchone()
        if fila is None:
            return False

        cambios: dict[str, Any] = {
            "snapshot": {k: _serializar(v) for k, v in zip(columnas, fila)},
            "tipo_borrado": tipo,
        }
        if contexto:
            cambios["contexto"] = contexto

        cur.execute(
            "INSERT INTO audit_log "
            "(tabla, registro_id, accion, usuario_id, usuario_nombre, cambios) "
            "VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))",
            [
                tabla, registro_id, "DELETE",
                getattr(usuario, "id", None),
                getattr(usuario, "nombre", None) or getattr(usuario, "email", None),
                json.dumps(cambios, ensure_ascii=False),
            ],
        )
    return True
