"""Vigencia efectiva de los registros GESCON.

Envuelve `gescon_vigencia.resolver_vigencias` con la parte que necesita la base.

**La resolución corre SIEMPRE sobre el universo completo de solicitudes
publicadas**, nunca sobre el subconjunto que filtró la petición: el relevo que
recorta a una fila puede venir de otra planta u otro contrato que el filtro
excluyó. Filas no publicadas o desistimientos no participan del recorrido:
conservan su `fecha_fin` cruda y `es_version_vigente = False`.
"""

from datetime import date

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services.asic_reglas import TIPOS_DE_REGISTRO
from apps.mercado_xm.services.gescon_vigencia import resolver_vigencias


def universo():
    """Las publicadas, en el orden que exige el resolutor.

    Ordena por `fecha_inicio` (cuándo tomó efecto) y NO por `fecha_solicitud`
    (cuándo se radicó): ordenar por radicación era el bug histórico que hacía
    aparecer una planta reubicada como activa en dos contratos a la vez.
    """
    return list(
        mx_models.AsicSolicitud.objects
        .filter(estado_solicitud="publicado")
        .exclude(tipo_solicitud="desistimiento")
        .select_related("proyecto")
        .order_by("fecha_inicio", "fecha_solicitud", "created_at")
    )


def anotar(solicitudes: list) -> list:
    """Pone `fecha_fin_efectiva` y `es_version_vigente` en cada instancia."""
    vigencias = resolver_vigencias(universo())
    for solicitud in solicitudes:
        vigencia = vigencias.get(solicitud.id)
        if vigencia is not None:
            solicitud.fecha_fin_efectiva = vigencia.fecha_fin_efectiva
            solicitud.es_version_vigente = vigencia.vigente
        else:
            solicitud.fecha_fin_efectiva = solicitud.fecha_fin
            solicitud.es_version_vigente = False
    return solicitudes


def versiones_vigentes(codigo_sic: str, en_fecha: date | None = None) -> list:
    """Las filas registro/modificación que son la versión vigente de un SIC.

    Puede devolver MÁS DE UNA: un SIC admite varias plantas coexistiendo
    (`reemplaza_anterior=False`).

    `en_fecha` deja solo las que siguen en vigor ese día — una planta que ya
    salió del SIC no debe contar como inscrita para una modificación posterior.
    Ojo con la diferencia: `es_version_vigente` significa «última versión de su
    SIC», no «en curso»; una fila con `fecha_fin` pasada sigue siendo la última.
    """
    todas = universo()
    vigencias = resolver_vigencias(todas)
    vigentes = [
        s for s in todas
        if s.codigo_sic_contrato == codigo_sic
        and s.tipo_solicitud in TIPOS_DE_REGISTRO
        and vigencias[s.id].vigente
    ]
    if en_fecha is None:
        return vigentes

    en_vigor = [
        s for s in vigentes if s.fecha_fin is None or s.fecha_fin >= en_fecha
    ]
    # Si a esa fecha ya no quedaba ninguna en vigor —caso: se está atrasando la
    # fecha de fin de un contrato que ya venció— se trabaja sobre las últimas
    # versiones, y las validaciones de fecha deciden si tiene sentido.
    return en_vigor or vigentes


def plantas_por_sic(codigos: set[str]) -> dict[str, str]:
    """Mapa código SIC → nombre(s) de planta, para mostrar.

    Se deriva de los registros que SÍ tienen proyecto, y sirve para poner la
    planta en filas que no llevan `proyecto_id` (p. ej. terminaciones) **sin
    almacenar el FK**: guardarlo reintroduciría el bug de Cumplimiento, que
    borraría la planta del mes en vez de prorratearla. Solo para mostrar.
    """
    if not codigos:
        return {}
    nombres: dict[str, list[str]] = {}
    consulta = (
        mx_models.AsicSolicitud.objects
        .filter(
            codigo_sic_contrato__in=codigos,
            proyecto__isnull=False,
            tipo_solicitud__in=TIPOS_DE_REGISTRO,
        )
        .select_related("proyecto")
    )
    for solicitud in consulta:
        nombre = solicitud.proyecto.nombre_comercial if solicitud.proyecto else None
        if not nombre:
            continue
        bolsa = nombres.setdefault(solicitud.codigo_sic_contrato, [])
        if nombre not in bolsa:
            bolsa.append(nombre)
    return {sic: " · ".join(ns) for sic, ns in nombres.items()}


def enriquecer_planta(solicitudes: list) -> list:
    """Pone `planta_nombre` en las filas que no tienen proyecto resuelto."""
    for solicitud in solicitudes:
        solicitud.planta_nombre = (
            solicitud.proyecto.nombre_comercial if solicitud.proyecto_id else None
        )
    pendientes = {
        s.codigo_sic_contrato for s in solicitudes
        if not s.planta_nombre and s.codigo_sic_contrato
    }
    if not pendientes:
        return solicitudes
    mapa = plantas_por_sic(pendientes)
    for solicitud in solicitudes:
        if not solicitud.planta_nombre and solicitud.codigo_sic_contrato:
            solicitud.planta_nombre = mapa.get(solicitud.codigo_sic_contrato)
    return solicitudes


def preparar(solicitudes: list) -> list:
    """Enriquece y anota, que es lo que toda respuesta de ASIC necesita."""
    return anotar(enriquecer_planta(solicitudes))
