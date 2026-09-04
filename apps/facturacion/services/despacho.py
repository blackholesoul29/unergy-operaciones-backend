"""Persistencia del despacho mensual de XM."""

from django.db import transaction

from apps.mercado_xm import models as mx_models


@transaction.atomic
def guardar(periodo: str, por_contrato: dict, por_dia: dict, archivo: str) -> dict:
    """Reemplaza el despacho del período. Devuelve el resumen de la carga.

    Se BORRA lo anterior del período antes de insertar: XM reemite el archivo
    con correcciones y acumular dejaría energía duplicada. Va en una sola
    transacción para que un fallo a mitad no deje el mes vacío.
    """
    mx_models.DespachoContratoMensual.objects.filter(periodo=periodo).delete()
    mx_models.DespachoContratoDia.objects.filter(periodo=periodo).delete()

    mx_models.DespachoContratoMensual.objects.bulk_create([
        mx_models.DespachoContratoMensual(
            periodo=periodo,
            codigo_sic_contrato=codigo,
            kwh=round(datos["kwh"], 4),
            vendedor=datos["vendedor"],
            comprador=datos["comprador"],
            tipo=datos["tipo"],
            dias=len(datos["fechas"]) or None,
            fecha_min=min(datos["fechas"]) if datos["fechas"] else None,
            fecha_max=max(datos["fechas"]) if datos["fechas"] else None,
            archivo=archivo,
        )
        for codigo, datos in por_contrato.items()
    ])
    mx_models.DespachoContratoDia.objects.bulk_create([
        mx_models.DespachoContratoDia(
            periodo=periodo, codigo_sic_contrato=codigo, fecha=fecha, kwh=kwh
        )
        for (codigo, fecha), kwh in por_dia.items()
    ])

    return {
        "periodo": periodo,
        "contratos": len(por_contrato),
        "kwh_total": round(sum(d["kwh"] for d in por_contrato.values()), 2),
        "horas": 24,
        "archivo": archivo,
    }
