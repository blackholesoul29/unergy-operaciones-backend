"""Vinculación de un contrato de servicio con sus fronteras."""

from apps.fronteras import models as fr_models


class FronteraInvalida(ValueError):
    pass


def sincronizar(contrato, frontera_ids: list[int]) -> None:
    """Deja el contrato vinculado EXACTAMENTE a `frontera_ids`.

    Los ids repetidos colapsan al resolverlos contra la base, así que no se
    viola la restricción única de `contrato_frontera`.
    """
    if not frontera_ids:
        fr_models.ContratoFrontera.objects.filter(contrato_servicio=contrato).delete()
        return

    pedidas = set(frontera_ids)
    fronteras = list(
        fr_models.Frontera.objects.filter(
            pk__in=pedidas, deleted_at__isnull=True
        )
    )
    faltantes = pedidas - {f.id for f in fronteras}
    if faltantes:
        raise FronteraInvalida(
            f"Fronteras no encontradas: {sorted(faltantes)}"
        )

    # Si el contrato ya tiene proyecto, las fronteras tienen que ser de ESE
    # proyecto: el contrato es legal y la frontera es física, y no tiene
    # sentido vincular un punto de medida de otra planta.
    if contrato.proyecto_id is not None:
        ajenas = [
            f.id for f in fronteras if f.proyecto_id != contrato.proyecto_id
        ]
        if ajenas:
            raise FronteraInvalida(
                "Estas fronteras no pertenecen al proyecto del contrato: "
                f"{sorted(ajenas)}"
            )

    fr_models.ContratoFrontera.objects.filter(contrato_servicio=contrato).delete()
    fr_models.ContratoFrontera.objects.bulk_create([
        fr_models.ContratoFrontera(contrato_servicio=contrato, frontera=f)
        for f in fronteras
    ])
