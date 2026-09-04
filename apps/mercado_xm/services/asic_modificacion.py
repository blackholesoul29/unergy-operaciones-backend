"""Registrar una modificación sobre un contrato GESCON existente.

**Una modificación NO es un registro nuevo**: es otra versión del MISMO código
SIC. Lo único que puede cambiar es la fecha de fin, la planta inscrita, su
porcentaje de despacho y su modalidad de suministro. El resto se HEREDA de la
versión vigente — pedirlo de nuevo es ruido, y dejarlo vacío saca la fila de
Cumplimiento, que agrupa por `contrato_interno`.

La modificación no surte efecto antes de su fecha de entrada: se guarda como
`fecha_inicio` y el resolutor de vigencias recorta la versión anterior al día
previo.
"""

from datetime import date, timedelta

from django.db import transaction

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services import asic_vigencia
from apps.mercado_xm.services.asic_errores import NoEncontrado, ReglaAsic
from apps.mercado_xm.services.asic_reglas import (
    MODALIDADES_SUMINISTRO, fmt_fecha, fraccion, listado_plantas,
    nombre_planta, normalizar_modalidad_pago, validar_fecha_fin_vs_ppa,
    validar_flags_exclusivos,
)
from apps.proyectos import models as py_models

ESTADOS = ("borrador", "radicado", "publicado", "rechazado", "desistimiento")

CAMPOS_HEREDADOS = (
    "codigo_sic_contrato", "codigo_sic_vendedor", "codigo_sic_comprador",
    "cedula_agente_vendedor", "cedula_agente_comprador", "contrato_interno",
    "nombre_interno", "nombre_contacto_solicitante", "prioridad_limitacion",
    "tipo_mercado", "tipo_asignacion", "porcentaje_fncer", "contrato_ppa_id",
)


def _base(sic: str, activos: list, datos: dict):
    """La versión que esta modificación releva.

    Con una sola planta inscrita es evidente. Con varias hay que decir cuál, o
    no se sabe a qué fila sustituye.
    """
    saliente_id = datos.get("proyecto_saliente_id")
    if saliente_id is not None:
        elegida = next(
            (a for a in activos if a.proyecto_id == saliente_id), None
        )
        if elegida is None:
            raise ReglaAsic(
                f'La planta indicada como saliente no está inscrita en el SIC '
                f'"{sic}" al {fmt_fecha(datos["fecha_entrada"])}. '
                f"Plantas inscritas: {listado_plantas(activos)}."
            )
        return elegida

    if len(activos) == 1:
        return activos[0]

    proyecto_id = datos.get("proyecto_id")
    elegida = next(
        (a for a in activos
         if proyecto_id is not None and a.proyecto_id == proyecto_id),
        None,
    )
    if elegida is None:
        raise ReglaAsic(
            f'El SIC "{sic}" tiene {len(activos)} plantas inscritas a la vez '
            f"({listado_plantas(activos)}). Indica cuál de ellas modifica esta "
            "solicitud (proyecto_saliente_id): de lo contrario no se sabe a "
            "cuál releva."
        )
    return elegida


def _validar_porcentaje(valor) -> None:
    if valor is not None and not 0 <= valor <= 1:
        raise ReglaAsic(
            "El % de despacho se almacena como fracción 0-1 (0.85 = 85%). "
            f"Se recibió {valor}: un valor fuera de escala rompe el cálculo de "
            "Cumplimiento (generación × porcentaje_despacho)."
        )


def _modalidad(datos: dict, base, cambia_planta: bool) -> tuple[bool, bool]:
    """La modalidad es de la PLANTA, no del contrato.

    Una planta nueva que no la declara entra como normal; si la planta no
    cambia, se conserva la suya.
    """
    modalidad = datos.get("modalidad")
    if modalidad is not None and modalidad not in MODALIDADES_SUMINISTRO:
        raise ReglaAsic(
            f'Modalidad de suministro inválida: "{modalidad}". '
            f'Opciones: {", ".join(MODALIDADES_SUMINISTRO)}.'
        )
    if modalidad is None:
        return (
            bool(base.es_duplicado) and not cambia_planta,
            bool(base.uso_del_recurso) and not cambia_planta,
        )
    return modalidad == "duplicado", modalidad == "uso_recurso"


def _validar_vigencia(datos: dict, base, fecha_fin) -> None:
    entrada = datos["fecha_entrada"]
    if base.fecha_inicio is not None and entrada <= base.fecha_inicio:
        raise ReglaAsic(
            f"La modificación entraría en vigencia el {fmt_fecha(entrada)}, "
            f"pero la versión que modifica arranca el "
            f"{fmt_fecha(base.fecha_inicio)}. La fecha de entrada tiene que ser "
            "posterior al inicio de la versión vigente."
        )
    if fecha_fin is not None and entrada > fecha_fin:
        raise ReglaAsic(
            f"La fecha de entrada ({fmt_fecha(entrada)}) es posterior a la "
            f"fecha de fin ({fmt_fecha(fecha_fin)}): la modificación nacería "
            "vencida."
        )


def _validar_requerimiento(datos: dict, base) -> str:
    requerimiento = (datos.get("requerimiento_asic") or "").strip()
    if not requerimiento:
        raise ReglaAsic(
            "El número de requerimiento ASIC de la modificación es obligatorio."
        )
    if base.requerimiento_asic and requerimiento == base.requerimiento_asic.strip():
        raise ReglaAsic(
            f'El requerimiento "{requerimiento}" es el mismo de la versión '
            "vigente. Cada modificación se radica ante XM con un requerimiento "
            "nuevo (el código SIC sí se conserva)."
        )
    return requerimiento


def _resumen(datos, base, proyecto_id, porcentaje, fecha_fin, cambia_planta):
    cambios = []
    if cambia_planta:
        cambios.append(
            f"sale {nombre_planta(base.proyecto_id)} y "
            f"entra {nombre_planta(proyecto_id)}"
        )
    if fraccion(porcentaje) != fraccion(base.porcentaje_despacho):
        def pct(valor):
            f = fraccion(valor)
            return "—" if f is None else f"{f * 100:g}%"
        cambios.append(
            f"despacho {pct(base.porcentaje_despacho)} → {pct(porcentaje)}"
        )
    if fecha_fin != base.fecha_fin:
        cambios.append(
            f"fin {fmt_fecha(base.fecha_fin)} → {fmt_fecha(fecha_fin)}"
        )
    if not cambios:
        cambios.append("sin cambios de planta, % ni fecha de fin")
    return (
        f'Desde el {fmt_fecha(datos["fecha_entrada"])}: '
        + "; ".join(cambios) + "."
    )


def crear(datos: dict) -> dict:
    """Devuelve `{modificacion, saliente, resumen}`."""
    sic = (datos.get("codigo_sic_contrato") or "").strip()
    if not sic:
        raise ReglaAsic(
            "El código SIC del contrato a modificar es obligatorio."
        )

    activos = asic_vigencia.versiones_vigentes(
        sic, en_fecha=datos["fecha_entrada"]
    )
    if not activos:
        raise NoEncontrado(
            f'No hay ningún registro publicado y vigente con el código SIC '
            f'"{sic}". Una modificación solo se hace sobre un contrato ya '
            "registrado: revisa el código, o crea primero el registro."
        )

    base = _base(sic, activos, datos)

    # Ausente = se hereda de la versión vigente.
    proyecto_id = (
        datos["proyecto_id"] if datos.get("proyecto_id") is not None
        else base.proyecto_id
    )
    fecha_fin = (
        datos["fecha_fin"] if datos.get("fecha_fin") is not None
        else base.fecha_fin
    )
    porcentaje = (
        datos["porcentaje_despacho"]
        if datos.get("porcentaje_despacho") is not None
        else base.porcentaje_despacho
    )
    _validar_porcentaje(datos.get("porcentaje_despacho"))

    cambia_planta = proyecto_id != base.proyecto_id
    if cambia_planta:
        _validar_planta_nueva(sic, proyecto_id, base, activos)

    es_duplicado, uso_del_recurso = _modalidad(datos, base, cambia_planta)
    _validar_vigencia(datos, base, fecha_fin)
    requerimiento = _validar_requerimiento(datos, base)
    estado = _validar_estado(datos)

    nueva = mx_models.AsicSolicitud(
        tipo_solicitud="modificacion",
        estado_solicitud=estado,
        requerimiento_asic=requerimiento,
        fecha_solicitud=datos.get("fecha_solicitud") or date.today(),
        fecha_inicio=datos["fecha_entrada"],
        fecha_fin=fecha_fin,
        proyecto_id=proyecto_id,
        porcentaje_despacho=porcentaje,
        es_duplicado=es_duplicado,
        uso_del_recurso=uso_del_recurso,
        link_archivo=datos.get("link_archivo"),
        observaciones=datos.get("observaciones"),
        # La modalidad de PAGO es del contrato, no de la planta: se conserva
        # aunque entre otra planta, salvo que la modificación diga otra cosa.
        modalidad_pago=(
            normalizar_modalidad_pago(datos.get("modalidad_pago"))
            or base.modalidad_pago
        ),
        **{campo: getattr(base, campo) for campo in CAMPOS_HEREDADOS},
    )

    saliente = _fijar_relevo(nueva, base, activos, datos, cambia_planta)
    validar_flags_exclusivos(es_duplicado, uso_del_recurso)

    with transaction.atomic():
        nueva.save()
        validar_fecha_fin_vs_ppa(nueva)
        if saliente is not None:
            saliente.save(update_fields=["fecha_fin"])

    return {
        "modificacion": nueva,
        "saliente": saliente,
        "resumen": _resumen(
            datos, base, proyecto_id, porcentaje, fecha_fin, cambia_planta
        ),
    }


def _validar_planta_nueva(sic, proyecto_id, base, activos) -> None:
    if proyecto_id is not None and not py_models.Proyecto.objects.filter(
        pk=proyecto_id
    ).exists():
        raise NoEncontrado(f"La planta {proyecto_id} no existe.")
    ya = next(
        (a for a in activos if a.proyecto_id == proyecto_id and a.id != base.id),
        None,
    )
    if ya is not None:
        raise ReglaAsic(
            f'{nombre_planta(proyecto_id)} ya está inscrita en el SIC "{sic}". '
            "Para cambiarle el % o la fecha, modifica esa planta directamente."
        )


def _validar_estado(datos: dict) -> str:
    estado = datos.get("estado_solicitud")
    if estado not in ESTADOS:
        raise ReglaAsic(
            f'Estado inválido: "{estado}". Opciones: {", ".join(ESTADOS)}.'
        )
    return estado


def _fijar_relevo(nueva, base, activos, datos, cambia_planta):
    """Decide `reemplaza_anterior` y, si toca, cierra la planta que sale.

    Tres casos, y confundirlos rompe la coexistencia del SIC:

    1. Misma planta → supersesión en sitio: el resolutor recorta la versión
       anterior de esa planta. Se conserva su flag para no alterar la
       coexistencia que ya tenía.
    2. Cambia la planta y era la única → relevo limpio. No se toca la fila
       vieja: el resolutor la recorta a la fecha de entrada menos un día.
    3. Cambia la planta y hay OTRAS inscritas → un relevo global se las
       llevaría por delante. La nueva entra coexistiendo y se cierra SOLO la
       que sale.
    """
    otras = [a for a in activos if a.id != base.id]
    if not cambia_planta:
        nueva.reemplaza_anterior = bool(base.reemplaza_anterior)
        return None
    if not otras:
        nueva.reemplaza_anterior = True
        return None

    nueva.reemplaza_anterior = False
    corte = datos["fecha_entrada"] - timedelta(days=1)
    if base.fecha_fin is None or base.fecha_fin > corte:
        base.fecha_fin = corte
    return base
