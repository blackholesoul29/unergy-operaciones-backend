"""Importación masiva de generación diaria.

El proyecto se resuelve por `proyecto_id` si viene; si no, por nombre difuso
(`apps/comun/proyecto_matching`), que es como llegan los datos del Excel.
"""

from django.db import transaction

from apps.comun import proyecto_matching
from apps.proyectos import models as py_models

# Campos que un upsert puede actualizar. `proyecto` y `fecha` son la clave y no
# se tocan.
CAMPOS = ("kwh_real", "kwh_p90", "kwh_autoconsumo", "fuente", "notas")


@transaction.atomic
def importar(items: list[dict], sobrescribir: bool) -> dict:
    """Devuelve `{insertados, actualizados, omitidos, errores}`.

    Con `sobrescribir=False` los duplicados se OMITEN en vez de fallar: la
    importación suele traer meses solapados y abortar por eso obligaría a
    recortar el archivo a mano.

    Un fallo de una fila se reporta y se sigue: el resto del archivo es válido.
    """
    cache: dict[str, object] = {}
    insertados = actualizados = omitidos = 0
    errores: list[str] = []

    for item in items:
        try:
            proyecto_id = item.get("proyecto_id")
            if not proyecto_id:
                nombre = item.get("proyecto_nombre_externo") or ""
                if nombre not in cache:
                    cache[nombre] = proyecto_matching.buscar_por_nombre(nombre)
                proyecto = cache[nombre]
                if proyecto is None:
                    errores.append(
                        f"No se encontró proyecto para '{nombre}' en "
                        f'{item["fecha"]}'
                    )
                    omitidos += 1
                    continue
                proyecto_id = proyecto.id

            existente = py_models.GeneracionDiaria.objects.filter(
                proyecto_id=proyecto_id, fecha=item["fecha"]
            ).first()

            if existente is not None:
                if not sobrescribir:
                    omitidos += 1
                    continue
                # Solo se pisan los campos que VIENEN: un `None` en el archivo
                # significa «no informado», no «bórralo».
                campos = [
                    c for c in CAMPOS if item.get(c) is not None
                ]
                for campo in campos:
                    setattr(existente, campo, item[campo])
                if campos:
                    existente.save(update_fields=campos)
                actualizados += 1
                continue

            py_models.GeneracionDiaria.objects.create(
                proyecto_id=proyecto_id, fecha=item["fecha"],
                **{c: item.get(c) for c in CAMPOS},
            )
            insertados += 1
        except Exception as exc:
            errores.append(f'Error en {item.get("fecha")}: {exc}')
            omitidos += 1

    return {
        "insertados": insertados,
        "actualizados": actualizados,
        "omitidos": omitidos,
        "errores": errores,
    }
