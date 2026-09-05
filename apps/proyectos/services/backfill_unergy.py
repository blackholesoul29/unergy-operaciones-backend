"""Backfill de `sub_project` y `fecha_entrada_operacion` desde la API de Unergy.

Puerto de `app/services/proyectos_backfill_unergy.py`.

Formas de uso:

  - `sincronizar_datos_unergy_si_aplica(proyecto)` — UN solo proyecto, aplica de
    inmediato y **nunca lanza**: se llama al crear o confirmar un proyecto, para
    que los nuevos no vuelvan a acumular estos vacíos. Si la API falla, está
    lenta o no hay match seguro, el proyecto queda como estaba.
  - `backfill_sub_project_unergy(apply=...)` — corrida masiva sobre el backlog.
  - `backfill_fecha_entrada_operacion_unergy(apply=...)` — igual, para la fecha.

**Un `sub_project` ya vinculado gana sobre el match por nombre.** Antes, si ese
tópico no aparecía en el listado ACTUAL de Unergy —ausencia temporal, filtro
distinto—, el código caía igual al fallback difuso e ignoraba el vínculo ya
confirmado: podía asignar la fecha de OTRO proyecto en vez de reportar que
Unergy no trajo dato.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from apps.comun.nombre_matching import mejor_candidato
from apps.energia.services.comercializacion import fetch_unergy_projects, unergy_token
from apps.proyectos.models import Proyecto

logger = logging.getLogger("operaciones.proyectos.unergy")

UMBRAL_SEGURO = 0.95


def _parse_fecha(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)[:10]).date()
    except ValueError:
        return None


def _candidatos_unergy(unergy_proyectos: list[dict]) -> list[tuple]:
    return [
        (up, [n for n in (up.get("nombre_proyecto"), up.get("nombre_corto")) if n])
        for up in unergy_proyectos
    ]


def _buscar_topico_seguro(
    nombre_comercial: str, proyecto_id: int, candidatos: list[tuple],
) -> tuple[str | None, str | None, float, str | None]:
    """(topico, nombre_unergy, score, motivo_rechazo). topico es None si no
    hay match seguro o si el topico ya está en uso por otro proyecto."""
    item, score = mejor_candidato(nombre_comercial, candidatos)
    if not item or score < UMBRAL_SEGURO:
        motivo = f"sin match con score >= {UMBRAL_SEGURO}"
        if item:
            motivo += f" (mejor candidato: {item.get('nombre_proyecto')!r} score={score:.2f})"
        return None, None, score, motivo

    topico = item.get("nombre_topico")
    conflicto = Proyecto.objects.filter(sub_project=topico).exclude(pk=proyecto_id).first()
    if conflicto:
        return None, None, score, f"topico '{topico}' ya asignado a otro proyecto (ID {conflicto.id})"

    return topico, item.get("nombre_proyecto"), score, None


def backfill_sub_project_unergy(apply: bool = False) -> dict:
    """Corrida masiva sobre todos los proyectos sin sub_project. Ver
    scripts/backfill_sub_project_unergy.py para el CLI (dry-run por defecto)."""
    sin_id = list(
        Proyecto.objects
        .filter(deleted_at__isnull=True, sub_project__isnull=True)
        .order_by("nombre_comercial")
    )
    if not sin_id:
        return {"ok": True, "revisados": 0, "asignados": [], "sin_match_seguro": []}

    try:
        token = unergy_token()
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo autenticar contra la API de Unergy: {exc}"}

    unergy_proyectos = fetch_unergy_projects(token)
    if not unergy_proyectos:
        return {"ok": False, "error": "La API de Unergy no devolvió proyectos"}

    candidatos = _candidatos_unergy(unergy_proyectos)

    asignados: list[dict] = []
    sin_match_seguro: list[dict] = []
    a_guardar: list[Proyecto] = []

    for p in sin_id:
        topico, unergy_nombre, score, motivo = _buscar_topico_seguro(
            p.nombre_comercial, p.id, candidatos)
        if not topico:
            sin_match_seguro.append({"proyecto_id": p.id, "nombre": p.nombre_comercial, "motivo": motivo})
            continue
        asignados.append({
            "proyecto_id": p.id, "nombre": p.nombre_comercial,
            "topico": topico, "unergy_nombre": unergy_nombre, "score": round(score, 2),
        })
        if apply:
            p.sub_project = topico
            a_guardar.append(p)

    if a_guardar:
        Proyecto.objects.bulk_update(a_guardar, ["sub_project"])

    return {
        "ok": True,
        "revisados": len(sin_id),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def backfill_fecha_entrada_operacion_unergy(apply: bool = False) -> dict:
    """Corrida masiva sobre todos los proyectos sin fecha_entrada_operacion
    (tengan o no sub_project ya asignado). Ver
    scripts/backfill_fecha_entrada_operacion_unergy.py para el CLI
    (dry-run por defecto)."""
    sin_fecha = list(
        Proyecto.objects
        .filter(deleted_at__isnull=True, fecha_entrada_operacion__isnull=True)
        .order_by("nombre_comercial")
    )
    if not sin_fecha:
        return {"ok": True, "revisados": 0, "asignados": [], "sin_match_seguro": []}

    try:
        token = unergy_token()
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo autenticar contra la API de Unergy: {exc}"}

    unergy_proyectos = fetch_unergy_projects(token)
    if not unergy_proyectos:
        return {"ok": False, "error": "La API de Unergy no devolvió proyectos"}

    por_topico = {up.get("nombre_topico"): up for up in unergy_proyectos if up.get("nombre_topico")}
    candidatos = _candidatos_unergy(unergy_proyectos)

    asignados: list[dict] = []
    sin_match_seguro: list[dict] = []
    a_guardar: list[Proyecto] = []

    for p in sin_fecha:
        # Si ya tiene sub_project, el vínculo con Unergy ya está confirmado --
        # no hace falta (ni conviene) volver a emparejar por nombre. Antes, si
        # ese tópico no aparecía en el listado ACTUAL de Unergy (ausencia
        # temporal, filtro distinto, etc.), el código caía igual al fallback
        # difuso por nombre e ignoraba el vínculo ya confirmado -- podía
        # asignar la fecha de un proyecto distinto en vez de reportar
        # simplemente que Unergy no trajo dato para ese sub_project.
        motivo = None
        if p.sub_project:
            item = por_topico.get(p.sub_project)
            if item is None:
                motivo = f"sub_project '{p.sub_project}' ya vinculado, pero Unergy no lo trae en el listado actual"
        else:
            topico, _unergy_nombre, _score, motivo = _buscar_topico_seguro(
                p.nombre_comercial, p.id, candidatos)
            item = por_topico.get(topico) if topico else None

        fecha = _parse_fecha(item.get("fecha_entrada_operacion")) if item else None
        if fecha is None:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": motivo or "Unergy no tiene fecha_entrada_operacion para este proyecto",
            })
            continue

        asignados.append({
            "proyecto_id": p.id, "nombre": p.nombre_comercial,
            "fecha_entrada_operacion": fecha.isoformat(),
        })
        if apply:
            p.fecha_entrada_operacion = fecha
            a_guardar.append(p)

    if a_guardar:
        Proyecto.objects.bulk_update(a_guardar, ["fecha_entrada_operacion"])

    return {
        "ok": True,
        "revisados": len(sin_fecha),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def sincronizar_datos_unergy_si_aplica(proyecto: Proyecto) -> str | None:
    """Best-effort para UN proyecto, en el momento de crearlo/confirmarlo
    (ver create_proyecto/confirmar_proyecto_pendiente en
    app/api/v1/proyectos.py) -- reemplaza el ciclo de "correr el script a
    mano cada tanto" para que los proyectos nuevos no vuelvan a acumular
    estos vacíos. Llena `sub_project` y/o `fecha_entrada_operacion`, lo que
    falte, en una sola consulta a la API (evita pedirla dos veces si un
    proyecto nuevo necesita ambos).

    Nunca sobreescribe un valor ya cargado, y nunca lanza: si la API de
    Unergy falla, está lenta, o no hay match seguro, el proyecto simplemente
    queda como estaba -- no bloquea la creación del proyecto en ningún caso.
    Retorna el topico si se asignó uno nuevo (no si solo se llenó la fecha),
    o None."""
    necesita_topico = not proyecto.sub_project
    necesita_fecha = proyecto.fecha_entrada_operacion is None
    if not necesita_topico and not necesita_fecha:
        return None
    try:
        token = unergy_token()
        unergy_proyectos = fetch_unergy_projects(token)
        if not unergy_proyectos:
            return None

        topico = proyecto.sub_project
        if necesita_topico:
            candidatos = _candidatos_unergy(unergy_proyectos)
            topico, _unergy_nombre, _score, _motivo = _buscar_topico_seguro(
                proyecto.nombre_comercial, proyecto.id, candidatos,
            )

        item = next((up for up in unergy_proyectos if up.get("nombre_topico") == topico), None) if topico else None
        if item is None:
            return None

        topico_asignado = None
        campos = []
        if necesita_topico and topico:
            proyecto.sub_project = topico
            topico_asignado = topico
            campos.append("sub_project")
        if necesita_fecha:
            fecha = _parse_fecha(item.get("fecha_entrada_operacion"))
            if fecha:
                proyecto.fecha_entrada_operacion = fecha
                campos.append("fecha_entrada_operacion")

        if campos:
            proyecto.save(update_fields=campos)
        return topico_asignado
    except Exception:
        logger.warning(
            "No se pudo sincronizar datos de Unergy para proyecto %s (%s)",
            proyecto.id, proyecto.nombre_comercial, exc_info=True,
        )
        return None
