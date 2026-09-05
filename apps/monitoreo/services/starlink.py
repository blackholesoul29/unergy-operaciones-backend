"""Reglas de negocio de las facturas Starlink.

La regeneración de líneas es lo único que no es cálculo puro: escribe. Vive acá
y no en la vista porque la disparan DOS caminos distintos —guardar una factura y
editar el catálogo de mapeos— y reimplementarla en los dos es como se
desincronizan.
"""

import json

from django.db import transaction

from apps.monitoreo import models as mo_models
from apps.monitoreo.services.starlink_resolver import resolver_lineas


@transaction.atomic
def regenerar_lineas(factura) -> None:
    """(Re)genera `starlink_factura_linea` de una factura desde su `agrupado_json`.

    Cada sitio se resuelve contra el catálogo `starlink_mapeo_sitio` por nombre.
    Se borran las líneas anteriores en vez de actualizarlas: el agrupado puede
    haber cambiado de forma y un merge fila a fila dejaría huérfanas.
    """
    mapeos = [
        {"patron": m.patron, "proyecto_id": m.proyecto_id, "excluido": m.excluido}
        for m in mo_models.StarlinkMapeoSitio.objects.filter(activo=True)
    ]
    mo_models.StarlinkFacturaLinea.objects.filter(factura=factura).delete()
    mo_models.StarlinkFacturaLinea.objects.bulk_create([
        mo_models.StarlinkFacturaLinea(
            factura=factura,
            proyecto_id=linea["proyecto_id"],
            excluido=linea["excluido"],
            descripcion=linea["descripcion"],
            sin_iva=linea["sin_iva"],
            iva=linea["iva"],
            monto_total=linea["monto_total"],
        )
        for linea in resolver_lineas(json.loads(factura.agrupado_json), mapeos)
    ])


def regenerar_todas_las_facturas() -> int:
    """Reprocesa todas las facturas guardadas. Devuelve cuántas.

    Se llama al tocar el catálogo de mapeos: un patrón nuevo o desactivado
    cambia a qué proyecto se imputa cada línea de CUALQUIER período ya guardado.
    """
    facturas = list(mo_models.StarlinkFactura.objects.all())
    for factura in facturas:
        regenerar_lineas(factura)
    return len(facturas)
