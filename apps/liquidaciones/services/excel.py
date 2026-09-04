"""Carga masiva del panel de seguimiento contable desde Excel.

`ponytail: el loader sigue en SQLAlchemy`. `app/utils/liquidaciones_loader.py`
son 966 líneas que leen el Excel, emparejan proyectos e inversionistas por
nombre difuso y escriben mandatos, costos y facturas. Reescribirlo contra el ORM
de Django es un trabajo aparte, con riesgo real de divergencia silenciosa en el
emparejamiento — y es UN endpoint.

Se le abre su propia sesión de SQLAlchemy, que es la misma base a la que apunta
Django. Funciona porque el loader es autónomo: hace su propio `commit` y no
comparte transacción con nada del request.

**Se porta cuando desaparezca el último lector FastAPI de estas tablas**, junto
con el resto de `liquidaciones`. Mientras tanto, un `dry_run=true` permite
verificar la carga sin escribir.
"""

import os
import tempfile

TIPOS_VENTA = ("ppa", "autoconsumo")


class TipoVentaInvalido(ValueError):
    pass


def _booleano(valor: str | None) -> bool:
    return (valor or "").strip().lower() in ("true", "1", "yes", "on")


def cargar(contenido: bytes, hoja: str, periodo_iso: str, *,
           tipo_venta: str, limpiar: str, dry_run: str, usuario_id: int) -> dict:
    from app.core.database import SessionLocal
    from app.utils.liquidaciones_loader import (
        cargar_desde_db, leer_hoja, leer_hoja_autoconsumo,
    )

    tipo_venta = (tipo_venta or "ppa").strip().lower()
    if tipo_venta not in TIPOS_VENTA:
        raise TipoVentaInvalido("tipo_venta debe ser 'ppa' o 'autoconsumo'")

    temporal = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    try:
        temporal.write(contenido)
        temporal.flush()
        temporal.close()

        lector = (
            leer_hoja_autoconsumo if tipo_venta == "autoconsumo" else leer_hoja
        )
        filas, mapa_er = lector(temporal.name, hoja)

        sesion = SessionLocal()
        try:
            return cargar_desde_db(
                db=sesion,
                filas=filas,
                er_map=mapa_er,
                periodo_date=periodo_iso,
                limpiar=_booleano(limpiar),
                dry_run=_booleano(dry_run),
                usuario_id=usuario_id,
                tipo_venta=tipo_venta,
            )
        finally:
            sesion.close()
    finally:
        try:
            os.unlink(temporal.name)
        except OSError:
            pass
