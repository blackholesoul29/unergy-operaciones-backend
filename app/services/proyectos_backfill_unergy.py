"""Backfill de datos de la plataforma Unergy original (no Quoia ni Solenium)
hacia `Proyecto`: `sub_project` ("API ID Unergy") y `fecha_entrada_operacion`
(COD -- Commercial Operation Date, tal cual la registra Unergy).

Reemplaza la carga manual que antes hacia scripts/cargar_topics_tsf.py desde
un JSON exportado a mano (data/NOMBRE TOPIC.json, con datos duplicados y
entradas basura) -- ahora consulta la API en vivo
(comercializacion.fetch_unergy_projects).

A diferencia de los "pendientes" de Fronteras/Proyectos (Quoia/Sun Factory),
que muestran sugerencias para confirmar a mano, este backfill NO tiene paso
de revisión: solo asigna cuando el match es casi exacto
(score >= UMBRAL_SEGURO). Se probó en vivo contra los 124 proyectos sin este
dato (2026-07-28): con umbral 0.95 hay un salto limpio -- 16 matches en
score=1.00 y el resto por debajo de 0.91, todos confirmados como falsos
positivos (nombres parecidos por palabras sueltas como "Occidente"/"Sur",
no el mismo proyecto). Por eso el umbral es deliberadamente estricto: mejor
dejar un proyecto sin ID que asignarle uno equivocado sin que nadie lo revise.

`fecha_entrada_operacion` se resuelve distinto según el caso: si el proyecto
YA tiene `sub_project`, se busca el registro de Unergy por `nombre_topico`
exacto (sin ambigüedad, no hace falta el emparejamiento difuso); si no lo
tiene, se usa el mismo emparejamiento y umbral que para `sub_project`.

Formas de uso:
  - `sincronizar_datos_unergy_si_aplica(proyecto, db)` -- un solo proyecto,
    siempre aplica de inmediato (sin dry-run) y nunca lanza excepción; se usa
    en el momento de crear/confirmar un proyecto (ver app/api/v1/proyectos.py)
    para que los proyectos nuevos no vuelvan a acumular estos vacíos. Llena
    `sub_project` y/o `fecha_entrada_operacion`, lo que falte, en una sola
    consulta a la API.
  - `backfill_sub_project_unergy(db, apply=...)` -- corrida masiva (script),
    con reporte dry-run/apply, para el backlog de proyectos sin `sub_project`.
  - `backfill_fecha_entrada_operacion_unergy(db, apply=...)` -- igual, para
    el backlog de proyectos sin `fecha_entrada_operacion` (independiente de
    si ya tienen `sub_project` o no).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto
from app.services.comercializacion import unergy_token, fetch_unergy_projects
from app.utils.nombre_matching import mejor_candidato

logger = logging.getLogger(__name__)

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
    nombre_comercial: str, proyecto_id: int, candidatos: list[tuple], db: Session,
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
    conflicto = db.query(Proyecto).filter(Proyecto.sub_project == topico, Proyecto.id != proyecto_id).first()
    if conflicto:
        return None, None, score, f"topico '{topico}' ya asignado a otro proyecto (ID {conflicto.id})"

    return topico, item.get("nombre_proyecto"), score, None


def backfill_sub_project_unergy(db: Session, apply: bool = False) -> dict:
    """Corrida masiva sobre todos los proyectos sin sub_project. Ver
    scripts/backfill_sub_project_unergy.py para el CLI (dry-run por defecto)."""
    sin_id = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None), Proyecto.sub_project.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
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

    for p in sin_id:
        topico, unergy_nombre, score, motivo = _buscar_topico_seguro(p.nombre_comercial, p.id, candidatos, db)
        if not topico:
            sin_match_seguro.append({"proyecto_id": p.id, "nombre": p.nombre_comercial, "motivo": motivo})
            continue
        asignados.append({
            "proyecto_id": p.id, "nombre": p.nombre_comercial,
            "topico": topico, "unergy_nombre": unergy_nombre, "score": round(score, 2),
        })
        if apply:
            p.sub_project = topico

    if apply and asignados:
        db.commit()

    return {
        "ok": True,
        "revisados": len(sin_id),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def backfill_fecha_entrada_operacion_unergy(db: Session, apply: bool = False) -> dict:
    """Corrida masiva sobre todos los proyectos sin fecha_entrada_operacion
    (tengan o no sub_project ya asignado). Ver
    scripts/backfill_fecha_entrada_operacion_unergy.py para el CLI
    (dry-run por defecto)."""
    sin_fecha = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None), Proyecto.fecha_entrada_operacion.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
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

    for p in sin_fecha:
        # Si ya tiene sub_project, el vínculo con Unergy ya está confirmado --
        # no hace falta (ni conviene) volver a emparejar por nombre.
        item = por_topico.get(p.sub_project) if p.sub_project else None
        motivo = None
        if item is None:
            topico, _unergy_nombre, _score, motivo = _buscar_topico_seguro(p.nombre_comercial, p.id, candidatos, db)
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

    if apply and asignados:
        db.commit()

    return {
        "ok": True,
        "revisados": len(sin_fecha),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def sincronizar_datos_unergy_si_aplica(proyecto: Proyecto, db: Session) -> str | None:
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
                proyecto.nombre_comercial, proyecto.id, candidatos, db,
            )

        item = next((up for up in unergy_proyectos if up.get("nombre_topico") == topico), None) if topico else None
        if item is None:
            return None

        topico_asignado = None
        if necesita_topico and topico:
            proyecto.sub_project = topico
            topico_asignado = topico
        if necesita_fecha:
            fecha = _parse_fecha(item.get("fecha_entrada_operacion"))
            if fecha:
                proyecto.fecha_entrada_operacion = fecha

        db.commit()
        return topico_asignado
    except Exception:
        db.rollback()
        logger.warning(
            "No se pudo sincronizar datos de Unergy para proyecto %s (%s)",
            proyecto.id, proyecto.nombre_comercial, exc_info=True,
        )
        return None
