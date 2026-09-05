"""Consultas del módulo de facturas Starlink."""

import json

from apps.monitoreo import models as mo_models
from apps.proyectos import models as py_models


def _datos_de_proyectos(ids):
    """Nombre, código TSF y tipo de los proyectos citados, en UNA consulta.

    Se resuelve por lote y no por fila: el serializer necesita el nombre
    comercial de cada línea y hacerlo dentro de un `SerializerMethodField` sería
    un N+1 con tantas consultas como líneas tenga la factura.
    """
    if not ids:
        return {}
    return {
        p["id"]: p
        for p in py_models.Proyecto.objects.filter(id__in=ids).values(
            "id", "nombre_comercial", "codigo_tsf", "tipo_proyecto"
        )
    }


def build_factura(factura) -> dict:
    """La factura de un período con sus líneas y el proyecto de cada una resuelto."""
    lineas = list(
        mo_models.StarlinkFacturaLinea.objects.filter(factura=factura)
    )
    proyectos = _datos_de_proyectos(
        {l.proyecto_id for l in lineas if l.proyecto_id is not None}
    )

    return {
        "periodo": factura.periodo,
        "items": json.loads(factura.items_json),
        "agrupado": json.loads(factura.agrupado_json),
        "cargos_totales": float(factura.cargos_totales) if factura.cargos_totales else None,
        "suma_items": float(factura.suma_items),
        "updated_at": factura.updated_at.isoformat() if factura.updated_at else None,
        "lineas": [
            {
                "descripcion": l.descripcion,
                "proyecto_id": l.proyecto_id,
                "excluido": l.excluido,
                "nombre_comercial": proyectos.get(l.proyecto_id, {}).get("nombre_comercial"),
                "codigo_tsf": proyectos.get(l.proyecto_id, {}).get("codigo_tsf"),
                "tipo_proyecto": proyectos.get(l.proyecto_id, {}).get("tipo_proyecto"),
                "sin_iva": float(l.sin_iva),
                "iva": float(l.iva),
                "monto_total": float(l.monto_total),
            }
            for l in lineas
        ],
    }


def build_mapeo() -> list[dict]:
    """El catálogo sitio→proyecto con el nombre comercial resuelto."""
    filas = list(mo_models.StarlinkMapeoSitio.objects.order_by("patron"))
    proyectos = _datos_de_proyectos(
        {m.proyecto_id for m in filas if m.proyecto_id is not None}
    )
    return [
        {
            "id": m.id,
            "patron": m.patron,
            "proyecto_id": m.proyecto_id,
            "nombre_comercial": proyectos.get(m.proyecto_id, {}).get("nombre_comercial"),
            "activo": m.activo,
            "excluido": m.excluido,
        }
        for m in filas
    ]
