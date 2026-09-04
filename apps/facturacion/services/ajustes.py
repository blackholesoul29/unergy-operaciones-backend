"""Los tres ajustes manuales de la pantalla de facturación.

Agrupación de contratos, precio de bolsa del mes y orden de las facturas. Los
tres son decisiones de la usuaria que el cálculo respeta.
"""

from django.db import transaction

from apps.facturacion import models as fa_models
from apps.mercado_xm import models as mx_models


@transaction.atomic
def guardar_agrupaciones(filas: list[dict]) -> None:
    """Upsert por contrato. Un nombre vacío QUITA la asignación.

    Que el nombre vacío borre en vez de guardar cadena vacía es lo que hace que
    el contrato vuelva a agrupar por su PPA sin un endpoint aparte.
    """
    for fila in filas:
        codigo = (fila.get("codigo_sic_contrato") or "").strip()
        if not codigo:
            continue
        nombre = (fila.get("nombre") or "").strip()
        if not nombre:
            fa_models.FacturaAgrupacion.objects.filter(
                codigo_sic_contrato=codigo
            ).delete()
            continue
        fa_models.FacturaAgrupacion.objects.update_or_create(
            codigo_sic_contrato=codigo,
            defaults={"nombre": nombre, "porcentaje": fila.get("porcentaje")},
        )


def listar_agrupaciones() -> list[dict]:
    return [
        {
            "codigo_sic_contrato": a.codigo_sic_contrato,
            "nombre": a.nombre,
            "porcentaje": (
                float(a.porcentaje) if a.porcentaje is not None else None
            ),
        }
        for a in fa_models.FacturaAgrupacion.objects.order_by("nombre")
    ]


def leer_bolsa(anio: int, mes: int) -> float | None:
    fila = mx_models.PrecioBolsaMensual.objects.filter(
        **{"año": anio, "mes": mes}
    ).first()
    return float(fila.valor) if fila else None


def guardar_bolsa(anio: int, mes: int, valor: float | None) -> None:
    """Un valor nulo o no positivo BORRA el precio manual del mes."""
    consulta = mx_models.PrecioBolsaMensual.objects.filter(
        **{"año": anio, "mes": mes}
    )
    if valor is None or valor <= 0:
        consulta.delete()
        return
    fila = consulta.first()
    if fila is None:
        mx_models.PrecioBolsaMensual.objects.create(
            **{"año": anio, "mes": mes, "valor": valor}
        )
    else:
        fila.valor = valor
        fila.save(update_fields=["valor"])


@transaction.atomic
def guardar_orden(nombres: list[str]) -> int:
    """Reescribe el orden completo. Devuelve cuántas quedaron.

    Se reemplaza todo en vez de actualizar posición por posición: así no quedan
    huecos ni posiciones viejas de facturas que ya no existen.
    """
    fa_models.FacturaOrden.objects.all().delete()
    limpios = [(n or "").strip() for n in nombres]
    fa_models.FacturaOrden.objects.bulk_create([
        fa_models.FacturaOrden(nombre=nombre, orden=posicion)
        for posicion, nombre in enumerate(limpios) if nombre
    ])
    return sum(1 for n in limpios if n)


def limpiar_orden() -> None:
    fa_models.FacturaOrden.objects.all().delete()


def marcar_emitida(nombre: str, periodo: str, emitida: bool,
                   numero: str | None, quien: str | None) -> None:
    consulta = fa_models.FacturaEmitida.objects.filter(
        nombre=nombre, periodo=periodo
    )
    if not emitida:
        consulta.delete()
        return
    fila = consulta.first()
    if fila is None:
        fa_models.FacturaEmitida.objects.create(
            nombre=nombre, periodo=periodo,
            numero_factura=numero, emitida_por=quien,
        )
    else:
        # Permite corregir el número sin desmarcar la factura.
        fila.numero_factura = numero
        fila.save(update_fields=["numero_factura"])
