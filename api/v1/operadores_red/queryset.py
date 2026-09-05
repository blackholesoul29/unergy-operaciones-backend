"""Consultas de operadores de red."""

from django.db.models import Count, Q

from apps.fronteras import models as fr_models


def con_conteo_de_fronteras():
    """Operadores con sus contactos y cuántas fronteras VIVAS tienen colgando.

    El conteo se anota en la consulta con un `filter` sobre el `Count`: hacerlo
    por fila serían tantas consultas como operadores, y contar las borradas
    (`deleted_at`) infla el número que se muestra en pantalla.
    """
    return (
        fr_models.OperadorRed.objects.prefetch_related("contactos")
        .annotate(
            fronteras_vinculadas=Count(
                "fronteras_por_operador_red_id",
                filter=Q(fronteras_por_operador_red_id__deleted_at__isnull=True),
                distinct=True,
            )
        )
        .order_by("nombre_comercial", "nombre_legal")
    )
