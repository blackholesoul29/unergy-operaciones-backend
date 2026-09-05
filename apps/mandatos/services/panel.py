"""Operaciones del panel de Mandatos: carga del ZIP, firma y reversión.

Las reglas puras (estados, parseo de nombres, matching de inversionista) están
en `reglas.py`, portado tal cual.
"""

from datetime import date

from django.db import transaction

from apps.mandatos import models as md_models
from apps.mandatos.services import pdfs as pdfs_service
from apps.mandatos.services.reglas import (
    match_inversionista, parsear_nombre_zip, transicion_valida,
)


class EstadoInvalido(ValueError):
    pass


class YaExiste(RuntimeError):
    pass


def periodo_a_fecha(periodo: str) -> date:
    """`"2025-05"` → `date(2025, 5, 1)`. Los mandatos se agrupan por mes."""
    try:
        anio, mes = periodo.split("-")
        return date(int(anio), int(mes), 1)
    except Exception as exc:
        raise ValueError(
            "Parámetro 'periodo' inválido, formato esperado YYYY-MM."
        ) from exc


def periodos_con_badge() -> list[dict]:
    """Los períodos con datos y en qué estado global está cada uno.

    `correcciones` gana sobre `cerrado`: si hay aunque sea un mandato con
    correcciones, el período pide atención aunque el resto esté enviado.
    """
    filas = md_models.Mandato.objects.values_list("periodo", "estado")
    por_periodo: dict[str, list[str]] = {}
    for periodo, estado in filas:
        por_periodo.setdefault(periodo.strftime("%Y-%m"), []).append(estado)

    salida = []
    for clave in sorted(por_periodo, reverse=True):
        estados = por_periodo[clave]
        if any(e == "con_correcciones" for e in estados):
            badge = "correcciones"
        elif all(e == "enviado_inversionista" for e in estados):
            badge = "cerrado"
        else:
            badge = "abierto"
        salida.append({"periodo": clave, "badge": badge})
    return salida


def marcar_firmado(mandato, ruta, nombre) -> None:
    """Asocia el PDF y sube el estado a «firmado» si la transición lo permite.

    La fecha de firma solo se pone si no había: reasociar un PDF no debe mover
    una fecha que ya se registró.
    """
    mandato.pdf_firmado_ruta = str(ruta)
    mandato.pdf_firmado_nombre = nombre
    mandato.fecha_firmado = mandato.fecha_firmado or date.today()
    campos = ["pdf_firmado_ruta", "pdf_firmado_nombre", "fecha_firmado"]
    if transicion_valida(mandato.estado, "firmado"):
        mandato.estado = "firmado"
        campos.append("estado")
    mandato.save(update_fields=campos)


def actualizar(mandato, cambios: dict) -> None:
    nuevo = cambios.get("estado")
    if nuevo and nuevo != mandato.estado and not transicion_valida(
        mandato.estado, nuevo
    ):
        raise EstadoInvalido(
            f"Transición de estado inválida: {mandato.estado} → {nuevo}."
        )
    for campo, valor in cambios.items():
        setattr(mandato, campo, valor)
    mandato.save(update_fields=list(cambios) or None)


@transaction.atomic
def cargar_zip(periodo: str, contenido: bytes) -> dict:
    """Crea un mandato por cada PDF del ZIP que no exista ya en el período.

    Los que ya existen se OMITEN, no se pisan: el ZIP se resube con correcciones
    y sobrescribir borraría el estado y el inversionista ya asignados a mano.
    """
    fecha = periodo_a_fecha(periodo)
    nombres = pdfs_service.pdfs_del_zip(contenido)
    maestra = [
        {"id": i.id, "nombre": i.nombre}
        for i in md_models.MandatoInversionista.objects.all()
    ]

    resumen = {
        "detectados": 0, "creados": 0, "omitidos": 0,
        "identificados_auto": 0, "sin_inversionista": 0,
        "no_parseables": [], "sugerencias": [],
    }

    for ruta in nombres:
        base = ruta.split("/")[-1]
        datos = parsear_nombre_zip(base)
        if not datos:
            resumen["no_parseables"].append(base)
            continue
        resumen["detectados"] += 1

        if md_models.Mandato.objects.filter(
            cmu=datos["cmu"], periodo=fecha
        ).exists():
            resumen["omitidos"] += 1
            continue

        inversionista_id, sugerencia, _score = match_inversionista(
            datos["inversionista"], maestra
        )
        mandato = md_models.Mandato.objects.create(
            cmu=datos["cmu"], periodo=fecha, proyecto=datos["proyecto"],
            tercero=datos["inversionista"], inversionista_id=inversionista_id,
            # Sin inversionista identificado el mandato no se puede enviar:
            # el estado lo refleja en vez de dejarlo como pendiente.
            estado="pendiente_envio" if inversionista_id else "sin_inversionista",
            archivo_zip_nombre=base,
        )
        resumen["creados"] += 1
        if inversionista_id:
            resumen["identificados_auto"] += 1
        else:
            resumen["sin_inversionista"] += 1
            if sugerencia:
                resumen["sugerencias"].append({
                    "mandato_id": mandato.id, "cmu": datos["cmu"],
                    "nombre_extraido": datos["inversionista"], **sugerencia,
                })

    pdfs_service.guardar_zip(periodo, contenido)
    return resumen


# Campos que un correo puede haber cambiado, con la clave donde la bitácora
# guardó su valor previo.
CAMPOS_REVERSIBLES = {
    "observacion": "observacion_previa",
    "fecha_firmado": "fecha_firmado_previa",
    "fecha_envio_inversionista": "fecha_envio_inversionista_previa",
    "correo_ref_envio": "correo_ref_envio_previo",
    "correo_ref_revisoria": "correo_ref_revisoria_previo",
}


@transaction.atomic
def revertir_correo(correo) -> list[str]:
    """Devuelve a su valor previo lo que este correo cambió en cada mandato.

    **No des-asocia `pdf_firmado_ruta` ni `pdf_firmado_nombre`**: revertir un
    estado no des-firma un documento que sí existe. Tampoco borra el PDF ni la
    fila de bitácora.
    """
    revertidos = []
    for accion in (correo.detalle or {}).get("acciones", []):
        if accion.get("resultado") != "aplicado":
            continue
        mandato = md_models.Mandato.objects.filter(
            pk=accion.get("mandato_id")
        ).first()
        if mandato is None:
            continue

        mandato.estado = accion["estado_previo"]
        campos = ["estado"]
        for campo, clave in CAMPOS_REVERSIBLES.items():
            if clave not in accion:
                continue
            valor = accion[clave]
            if campo == "fecha_envio_inversionista" and valor:
                valor = date.fromisoformat(valor)
            setattr(mandato, campo, valor)
            campos.append(campo)
        mandato.save(update_fields=campos)
        revertidos.append(mandato.cmu)

    correo.revertido = True
    # Se marca para revisión: alguien deshizo lo que la automatización aplicó y
    # conviene que quede a la vista.
    correo.requiere_revision = True
    correo.save(update_fields=["revertido", "requiere_revision"])
    return revertidos
