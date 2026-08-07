"""Backfill de `Proyecto.sub_project` ("API ID Unergy") por emparejamiento de
nombre contra el listado de proyectos de la plataforma Unergy original.

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

Dos formas de uso:
  - `backfill_sub_project_unergy(db, apply=...)` -- corrida masiva (script),
    con reporte dry-run/apply, para el backlog de proyectos ya existentes.
  - `asignar_sub_project_unergy_si_aplica(proyecto, db)` -- un solo proyecto,
    siempre aplica de inmediato (sin dry-run) y nunca lanza excepción; se usa
    en el momento de crear/confirmar un proyecto (ver app/api/v1/proyectos.py)
    para que los proyectos nuevos no vuelvan a acumular este vacío.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto
from app.services.comercializacion import unergy_token, fetch_unergy_projects
from app.utils.nombre_matching import mejor_candidato

logger = logging.getLogger(__name__)

UMBRAL_SEGURO = 0.95


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


def asignar_sub_project_unergy_si_aplica(proyecto: Proyecto, db: Session) -> str | None:
    """Best-effort para UN proyecto, en el momento de crearlo/confirmarlo
    (ver create_proyecto/confirmar_proyecto_pendiente en
    app/api/v1/proyectos.py) -- reemplaza el ciclo de "correr el script a
    mano cada tanto" para que los proyectos nuevos no vuelvan a acumular
    este vacío.

    Nunca sobreescribe (no hace nada si el proyecto ya tiene sub_project) y
    nunca lanza: si la API de Unergy falla, está lenta, o no hay match
    seguro, el proyecto simplemente queda como estaba -- no bloquea la
    creación del proyecto en ningún caso. Retorna el topico asignado, o
    None si no se asignó nada."""
    if proyecto.sub_project:
        return None
    try:
        token = unergy_token()
        unergy_proyectos = fetch_unergy_projects(token)
        if not unergy_proyectos:
            return None
        candidatos = _candidatos_unergy(unergy_proyectos)
        topico, _unergy_nombre, _score, _motivo = _buscar_topico_seguro(
            proyecto.nombre_comercial, proyecto.id, candidatos, db,
        )
        if not topico:
            return None
        proyecto.sub_project = topico
        db.commit()
        return topico
    except Exception:
        logger.warning(
            "No se pudo intentar asignar sub_project de Unergy para proyecto %s (%s)",
            proyecto.id, proyecto.nombre_comercial, exc_info=True,
        )
        return None
