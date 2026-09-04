"""Registrar la terminación de un contrato GESCON.

Misma dinámica que la modificación: se elige el SIC y la identidad del contrato
se hereda. Lo que NO se hereda es la planta — **una terminación se guarda sin
`proyecto_id` a propósito**: con planta, Cumplimiento borra esa planta del mes de
la terminación en vez de prorratearla hasta la fecha.
"""

from datetime import date

from django.db import transaction

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services import asic_vigencia
from apps.mercado_xm.services.asic_errores import NoEncontrado, ReglaAsic
from apps.mercado_xm.services.asic_modificacion import ESTADOS, _validar_estado
from apps.mercado_xm.services.asic_reglas import (
    auto_terminar, fmt_fecha, nombre_planta, validar_fecha_fin_vs_ppa,
)

CAMPOS_HEREDADOS = (
    "codigo_sic_contrato", "codigo_sic_vendedor", "codigo_sic_comprador",
    "contrato_interno", "nombre_interno", "prioridad_limitacion",
    "tipo_mercado", "tipo_asignacion", "contrato_ppa_id",
)


def crear(datos: dict) -> dict:
    """Devuelve `{terminacion, cerrados, resumen}`."""
    sic = (datos.get("codigo_sic_contrato") or "").strip()
    if not sic:
        raise ReglaAsic("El código SIC del contrato a terminar es obligatorio.")

    fecha = datos["fecha_terminacion"]
    activos = asic_vigencia.versiones_vigentes(sic, en_fecha=fecha)
    if not activos:
        raise NoEncontrado(
            f'No hay ningún registro publicado y vigente con el código SIC '
            f'"{sic}". Revisa el código: una terminación se radica sobre un '
            "contrato registrado."
        )

    # La identidad es del CONTRATO, no de una planta: sirve cualquier versión
    # vigente del SIC, prefiriendo una que sí tenga el contrato interno.
    base = next(
        (a for a in activos if (a.contrato_interno or "").strip()), activos[0]
    )

    inicios = [a.fecha_inicio for a in activos if a.fecha_inicio is not None]
    if inicios and fecha < min(inicios):
        raise ReglaAsic(
            f"La fecha de terminación ({fmt_fecha(fecha)}) es anterior al "
            f"inicio del contrato ({fmt_fecha(min(inicios))})."
        )

    requerimiento = (datos.get("requerimiento_asic") or "").strip() or None
    if (
        requerimiento and base.requerimiento_asic
        and requerimiento == base.requerimiento_asic.strip()
    ):
        raise ReglaAsic(
            f'El requerimiento "{requerimiento}" es el mismo del registro '
            "vigente. El código SIC sí se conserva, pero la terminación se "
            "radica con un requerimiento propio."
        )

    estado = _validar_estado(datos)

    nueva = mx_models.AsicSolicitud(
        tipo_solicitud="terminacion",
        estado_solicitud=estado,
        requerimiento_asic=requerimiento,
        fecha_solicitud=datos.get("fecha_solicitud") or date.today(),
        fecha_inicio=None,
        fecha_fin=fecha,
        proyecto_id=None,               # deliberado, ver docstring del módulo
        # Las cédulas son de la radicación; si no vienen, del registro.
        cedula_agente_vendedor=(
            datos.get("cedula_agente_vendedor") or base.cedula_agente_vendedor
        ),
        cedula_agente_comprador=(
            datos.get("cedula_agente_comprador") or base.cedula_agente_comprador
        ),
        link_archivo=datos.get("link_archivo"),
        observaciones=datos.get("observaciones"),
        reemplaza_anterior=True,
        es_duplicado=False,
        uso_del_recurso=False,
        **{campo: getattr(base, campo) for campo in CAMPOS_HEREDADOS},
    )

    with transaction.atomic():
        nueva.save()
        validar_fecha_fin_vs_ppa(nueva)
        cerrados = auto_terminar(nueva)

    return {
        "terminacion": nueva,
        "cerrados": cerrados,
        "resumen": _resumen(base, sic, fecha, estado, cerrados),
    }


def _resumen(base, sic, fecha, estado, cerrados) -> str:
    etiqueta = base.contrato_interno or base.nombre_interno or f"SIC {sic}"
    if cerrados:
        plantas = ", ".join(
            sorted({nombre_planta(c.proyecto_id) for c in cerrados})
        )
        detalle = (
            f"se cerró la vigencia de {len(cerrados)} registro(s): {plantas}"
        )
    elif estado == "publicado":
        detalle = "no había registros vigentes que cerrar"
    else:
        detalle = "queda en borrador: no cierra nada hasta que se publique"
    return (
        f"{etiqueta} (SIC {sic}) termina el {fmt_fecha(fecha)}; {detalle}."
    )
