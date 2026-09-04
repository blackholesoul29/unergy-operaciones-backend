"""Fusión de los contratos de representación duplicados.

El análisis puro está en `representacion_dedup.py` (portado tal cual); acá va lo
que escribe.

**Nunca sobreescribe un valor existente** y salta cualquier grupo donde dos
registros se contradigan: completar un dato ausente es seguro, elegir entre dos
respuestas distintas no.
"""

from django.db import transaction

from apps.clientes.services import documentos as documentos_service
from apps.contratos import models as ct_models
from apps.contratos.services.representacion_dedup import agrupar, analizar

SERVICIO = "representacion"
NOMBRE_ENLACE = "Enlace Drive del contrato"


def contratos_de_representacion() -> list:
    return list(
        ct_models.ContratoServicio.objects.filter(servicio_aplica=SERVICIO)
    )


@transaction.atomic
def fusionar(ids: list[int] | None = None) -> dict:
    """Fusiona los grupos limpios. `ids` limita a los grupos que los contengan."""
    contratos = contratos_de_representacion()
    por_id = {c.id: c for c in contratos}

    fusionados, eliminados, saltados = [], 0, []
    for grupo in agrupar(contratos):
        analisis = analizar(grupo)
        if not analisis["fusionable"]:
            saltados.append({
                "ids": [c.id for c in grupo],
                "conflictos": analisis["conflictos"],
            })
            continue
        if ids and not any(c.id in ids for c in grupo):
            continue

        conservado = por_id[analisis["conservar"]]
        campos = []
        for campo, valor in analisis["valores"].items():
            if campo == "enlace_drive":
                # No es una columna: es una propiedad de solo lectura sobre los
                # documentos comerciales, así que no admite `setattr`.
                documentos_service.set_enlace(
                    contrato_servicio_id=conservado.id, url=valor,
                    nombre=NOMBRE_ENLACE,
                )
                continue
            setattr(conservado, campo, valor)
            campos.append(campo)
        if campos:
            conservado.save(update_fields=campos)

        for contrato_id in analisis["eliminar"]:
            por_id[contrato_id].delete()
            eliminados += 1

        fusionados.append({
            "conservado": conservado.id,
            "eliminados": analisis["eliminar"],
            "campos_completados": sorted(analisis["valores"]),
        })

    return {
        "grupos_fusionados": len(fusionados),
        "contratos_eliminados": eliminados,
        "detalle": fusionados,
        "saltados_por_conflicto": saltados,
    }
