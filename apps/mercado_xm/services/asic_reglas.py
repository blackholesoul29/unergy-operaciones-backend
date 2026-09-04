"""Reglas de validación y efectos de los registros GESCON.

Todas trabajan sobre instancias de `AsicSolicitud` y ninguna sabe de HTTP.
"""

from datetime import date

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services.asic_errores import ReglaAsic
from apps.ppa import models as ppa_models

MODALIDADES_PAGO = ("plg", "plc")
MODALIDADES_SUMINISTRO = ("normal", "duplicado", "uso_recurso")

TIPOS_DE_REGISTRO = ("registro", "modificacion")


def fmt_fecha(dia: date | None) -> str:
    return dia.strftime("%d/%m/%Y") if dia else "sin fecha"


def fraccion(valor) -> float | None:
    """Normaliza a float con 4 decimales.

    Evita comparar `Decimal` contra `float` —`Decimal("0.85") != 0.85` en
    Python— al detectar si el porcentaje cambió de verdad.
    """
    return None if valor is None else round(float(valor), 4)


def normalizar_modalidad_pago(valor: str | None) -> str | None:
    """`plg` | `plc` | None.

    Es la modalidad de pago del CONTRATO en el que participa la planta; marcar
    el par PLG/PLC es lo que permite distinguir una planta repartida entre dos
    contratos de una duplicada de verdad.
    """
    if valor is None:
        return None
    limpio = valor.strip().lower()
    if not limpio:
        return None
    if limpio not in MODALIDADES_PAGO:
        raise ReglaAsic(
            f'Modalidad de pago inválida: "{valor}". '
            f'Opciones: {", ".join(MODALIDADES_PAGO)} (o vacío si no aplica).'
        )
    return limpio


def validar_flags_exclusivos(es_duplicado: bool, uso_del_recurso: bool) -> None:
    """«Compra en bolsa» y «Uso del recurso» son figuras distintas.

    La primera es compra real en el mercado spot; la segunda, el compromiso de
    pagarle al cliente a precio de bolsa una planta que entra al contrato. No
    pueden coexistir en un mismo registro.
    """
    if es_duplicado and uso_del_recurso:
        raise ReglaAsic(
            "Un registro no puede ser 'Compra en bolsa' y 'Uso del recurso' a la "
            "vez. Marca 'Compra en bolsa' si la planta coexiste en otro contrato "
            "con origen bolsa, o 'Uso del recurso' si el cliente está en bolsa y "
            "Unergy usa la planta para cumplir este contrato."
        )


def resolver_ppa(solicitud):
    """El PPA canónico de un registro: por FK, o casando el contrato interno."""
    if solicitud.contrato_ppa_id:
        return ppa_models.PpaContrato.objects.filter(
            pk=solicitud.contrato_ppa_id, deleted_at__isnull=True
        ).first()
    interno = (solicitud.contrato_interno or "").strip()
    if interno:
        return ppa_models.PpaContrato.objects.filter(
            numero_codigo_contrato=interno, deleted_at__isnull=True
        ).first()
    return None


def validar_fecha_fin_vs_ppa(solicitud) -> None:
    """Ningún registro puede terminar después que su contrato PPA macro.

    Evita que una planta quede «vigente» más allá de lo que permite el contrato
    comercial firmado, cuya `fecha_fin` es manual y es la fuente de verdad.
    """
    if solicitud.fecha_fin is None:
        return
    ppa = resolver_ppa(solicitud)
    if ppa is None or ppa.fecha_fin is None:
        return
    if solicitud.fecha_fin > ppa.fecha_fin:
        nombre = (
            ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
        )
        raise ReglaAsic(
            f"La fecha de fin ({solicitud.fecha_fin.isoformat()}) no puede ser "
            f'posterior a la del contrato PPA "{nombre}" '
            f"({ppa.fecha_fin.isoformat()}). Corrige la fecha o actualiza "
            f"primero el contrato macro."
        )


def auto_terminar(solicitud) -> list:
    """Estampa la fecha de fin de una terminación en los registros de su SIC.

    Los registros NO se marcan «terminado»: siguen «publicado» para que
    Cumplimiento los prorratee HASTA la fecha y los excluya DESPUÉS — así el
    histórico previo a la terminación queda intacto.

    **No toca la `fecha_fin` del contrato PPA comercial**, que es un campo
    manual. Inferirla de fechas sueltas en registros de ASIC resultó frágil:
    cualquier `fecha_fin` cargada en una planta por un motivo ajeno a una
    terminación real (p. ej. vigencia de registro GESCON) contaminaba el cierre
    del contrato completo. Si el contrato macro debe cerrarse, se edita en la
    pestaña de PPA.

    Devuelve los registros a los que efectivamente se les estampó la fecha: los
    que ya terminaban antes no se tocan, y se reportan a quien la radica.
    """
    if (
        solicitud.tipo_solicitud != "terminacion"
        or solicitud.estado_solicitud != "publicado"
        or not solicitud.codigo_sic_contrato
        or solicitud.fecha_fin is None
    ):
        return []

    corte = solicitud.fecha_fin
    objetivo = mx_models.AsicSolicitud.objects.filter(
        codigo_sic_contrato=solicitud.codigo_sic_contrato,
        estado_solicitud="publicado",
        tipo_solicitud__in=TIPOS_DE_REGISTRO,
    ).exclude(pk=solicitud.pk)

    cerrados = []
    for registro in objetivo:
        if registro.fecha_fin is None or registro.fecha_fin > corte:
            registro.fecha_fin = corte
            registro.save(update_fields=["fecha_fin"])
            cerrados.append(registro)
    return cerrados


def nombre_planta(proyecto_id: int | None) -> str:
    from apps.proyectos import models as py_models

    if proyecto_id is None:
        return "sin planta"
    nombre = (
        py_models.Proyecto.objects.filter(pk=proyecto_id)
        .values_list("nombre_comercial", flat=True).first()
    )
    return nombre or f"planta {proyecto_id}"


def listado_plantas(filas) -> str:
    return ", ".join(nombre_planta(f.proyecto_id) for f in filas)
