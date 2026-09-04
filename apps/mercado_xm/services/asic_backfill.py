"""Los dos backfills de GESCON. Ambos idempotentes y con `dry_run` por defecto.

`ponytail: siguen siendo endpoints POST, no management commands`. Según
`CLAUDE.md` un backfill de datos va en un comando; moverlo cambiaría el
contrato, y esta migración no cambia contratos. Son candidatos a
`manage.py backfill_gescon_*` cuando termine el port.
"""

from django.db import transaction
from django.db.models import Q

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services.asic_reglas import (
    TIPOS_DE_REGISTRO, auto_terminar, nombre_planta, resolver_ppa,
)

# Campos de identidad que una terminación hereda de los registros de su SIC.
CAMPOS_IDENTIDAD = (
    "contrato_interno", "nombre_interno", "codigo_sic_vendedor",
    "codigo_sic_comprador", "tipo_mercado", "tipo_asignacion",
)


def nombre_interno(dry_run: bool = True) -> dict:
    """Completa `nombre_interno` vacío copiándolo del PPA al que pertenece.

    De paso vincula `contrato_ppa_id` si faltaba. **No inventa nombres**: los
    que no tienen PPA con nombre se reportan sin tocar.
    """
    faltantes = list(
        mx_models.AsicSolicitud.objects
        .filter(Q(nombre_interno__isnull=True) | Q(nombre_interno__regex=r"^\s*$"))
        .filter(
            Q(contrato_ppa__isnull=False)
            | (
                Q(contrato_interno__isnull=False)
                & ~Q(contrato_interno__regex=r"^\s*$")
            )
        )
    )

    resueltos, sin_resolver = [], []
    for solicitud in faltantes:
        ppa = resolver_ppa(solicitud)
        nombre = (ppa.nombre_interno or "").strip() if ppa else ""
        if ppa and nombre:
            resueltos.append({
                "id": solicitud.id,
                "contrato_interno": solicitud.contrato_interno,
                "nombre_propuesto": nombre,
                "vincula_ppa_id": (
                    ppa.id if not solicitud.contrato_ppa_id else None
                ),
            })
        else:
            sin_resolver.append({
                "id": solicitud.id,
                "contrato_interno": solicitud.contrato_interno,
                "motivo": (
                    "sin PPA que casar" if not ppa
                    else "el PPA no tiene nombre_interno"
                ),
            })

    reporte = {
        "dry_run": dry_run,
        "total_sin_nombre": len(faltantes),
        "a_actualizar": len(resueltos),
        "sin_resolver": len(sin_resolver),
        "resueltos": resueltos,
        "no_resueltos": sin_resolver,
    }
    if dry_run:
        return reporte

    with transaction.atomic():
        for fila in resueltos:
            solicitud = mx_models.AsicSolicitud.objects.filter(
                pk=fila["id"]
            ).first()
            if solicitud is None:
                continue
            solicitud.nombre_interno = fila["nombre_propuesto"]
            campos = ["nombre_interno"]
            if fila["vincula_ppa_id"] and not solicitud.contrato_ppa_id:
                solicitud.contrato_ppa_id = fila["vincula_ppa_id"]
                campos.append("contrato_ppa")
            solicitud.save(update_fields=campos)

    reporte["ejecutado"] = True
    return reporte


def _fuentes_por_sic(codigos: set[str]) -> dict[str, list]:
    """Registros/modificaciones por SIC, del más reciente al más viejo.

    Ese orden es el que permite tomar «el primero que tenga cada dato».
    """
    fuentes: dict[str, list] = {}
    if not codigos:
        return fuentes
    consulta = (
        mx_models.AsicSolicitud.objects
        .filter(
            codigo_sic_contrato__in=codigos,
            tipo_solicitud__in=TIPOS_DE_REGISTRO,
        )
        .order_by("-fecha_inicio", "-id")
    )
    for solicitud in consulta:
        fuentes.setdefault(solicitud.codigo_sic_contrato, []).append(solicitud)
    return fuentes


def terminaciones(dry_run: bool = True) -> dict:
    """Deja las terminaciones ya registradas bien aplicadas. Dos cosas:

    1. **Completa su IDENTIDAD.** Hasta que existió `POST /asic/terminacion`,
       el formulario guardaba la terminación con SIC, fecha y cédulas y nada
       más: sin contrato ni nombre interno, así que salía en blanco en la tabla
       y en el Excel. Se rellenan desde los registros del MISMO SIC.
    2. **Estampa la FECHA** en los registros que quedaron sin recortar. La
       vigencia efectiva ya se deriva sola, así que esto NO cambia ningún
       cálculo: sirve para que la `fecha_fin` almacenada —la que se ve en la
       tabla y en el Excel— deje de decir 2030 cuando el contrato terminó.
       Reusa `auto_terminar`, la misma función que corre al guardar una
       terminación: una sola regla, no dos.

    No toca `proyecto_id`. Idempotente: solo llena vacíos y solo recorta hacia
    atrás.
    """
    filas = list(
        mx_models.AsicSolicitud.objects
        .filter(tipo_solicitud="terminacion", codigo_sic_contrato__isnull=False)
        .order_by("id")
    )
    fuentes = _fuentes_por_sic({f.codigo_sic_contrato for f in filas})

    resueltos, sin_resolver = [], []
    for terminacion in filas:
        candidatos = fuentes.get(terminacion.codigo_sic_contrato, [])
        if not candidatos:
            sin_resolver.append({
                "id": terminacion.id,
                "codigo_sic_contrato": terminacion.codigo_sic_contrato,
                "motivo": "no hay registros con ese código SIC",
            })
            continue
        cambios = _cambios_de_identidad(terminacion, candidatos)
        if cambios:
            resueltos.append({
                "id": terminacion.id,
                "codigo_sic_contrato": terminacion.codigo_sic_contrato,
                "fecha_fin": (
                    terminacion.fecha_fin.isoformat()
                    if terminacion.fecha_fin else None
                ),
                "cambios": cambios,
            })

    sin_recortar = _pendientes_de_recorte(filas, fuentes)

    reporte = {
        "dry_run": dry_run,
        "total_terminaciones": len(filas),
        "a_actualizar": len(resueltos),
        "sin_resolver": len(sin_resolver),
        "resueltos": resueltos,
        "no_resueltos": sin_resolver,
        "a_recortar": sum(len(s["registros"]) for s in sin_recortar),
        "sin_recortar": sin_recortar,
    }
    if dry_run:
        return reporte

    with transaction.atomic():
        for fila in resueltos:
            terminacion = mx_models.AsicSolicitud.objects.filter(
                pk=fila["id"]
            ).first()
            if terminacion is None:
                continue
            for campo, valor in fila["cambios"].items():
                setattr(terminacion, campo, valor)
            terminacion.save(update_fields=list(fila["cambios"]))
        for pendiente in sin_recortar:
            terminacion = mx_models.AsicSolicitud.objects.filter(
                pk=pendiente["id"]
            ).first()
            if terminacion is not None:
                auto_terminar(terminacion)

    reporte["ejecutado"] = True
    return reporte


def _cambios_de_identidad(terminacion, candidatos) -> dict:
    cambios: dict = {}
    for campo in CAMPOS_IDENTIDAD:
        if (getattr(terminacion, campo) or "").strip():
            continue
        valor = next(
            (
                v for v in
                ((getattr(c, campo) or "").strip() for c in candidatos)
                if v
            ),
            None,
        )
        if valor:
            cambios[campo] = valor

    if terminacion.prioridad_limitacion is None:
        prioridad = next(
            (
                c.prioridad_limitacion for c in candidatos
                if c.prioridad_limitacion is not None
            ),
            None,
        )
        if prioridad is not None:
            cambios["prioridad_limitacion"] = prioridad

    if terminacion.contrato_ppa_id is None:
        ppa_id = next(
            (c.contrato_ppa_id for c in candidatos if c.contrato_ppa_id), None
        )
        if ppa_id:
            cambios["contrato_ppa"] = ppa_id
    return cambios


def _pendientes_de_recorte(filas, fuentes) -> list[dict]:
    """Registros que una terminación publicada debería haber cerrado y no cerró.

    Mismo criterio que `auto_terminar`: fecha nula o posterior a la del cierre.
    """
    salida = []
    for terminacion in filas:
        if (
            terminacion.fecha_fin is None
            or terminacion.estado_solicitud != "publicado"
        ):
            continue
        pendientes = [
            {
                "id": c.id,
                "planta": nombre_planta(c.proyecto_id),
                "fecha_fin_actual": (
                    c.fecha_fin.isoformat() if c.fecha_fin else None
                ),
            }
            for c in fuentes.get(terminacion.codigo_sic_contrato, [])
            if c.estado_solicitud == "publicado"
            and (c.fecha_fin is None or c.fecha_fin > terminacion.fecha_fin)
        ]
        if pendientes:
            salida.append({
                "id": terminacion.id,
                "codigo_sic_contrato": terminacion.codigo_sic_contrato,
                "requerimiento_asic": terminacion.requerimiento_asic,
                "termina": terminacion.fecha_fin.isoformat(),
                "registros": pendientes,
            })
    return salida
