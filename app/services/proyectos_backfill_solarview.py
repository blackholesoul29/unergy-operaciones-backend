"""Backfill de `Proyecto.project_id_solarview` emparejando por nombre contra
`SolarViewClient.get_company_projects()`.

A diferencia de `project_id_solenium` (ver proyectos_backfill_solenium.py),
esta columna no tenía ningún mecanismo de escritura automática -- solo se
podía poblar a mano por SQL directo. Mismo criterio que el resto de backfills
de matching por nombre de esta sesión:
  - Si el proyecto ya tiene `project_id_solarview`, no se toca (nunca se
    sobreescribe un valor ya cargado).
  - Si no, se empareja por nombre contra el listado de SolarView
    (`mejor_candidato`, umbral 0.95).
  - `project_id_solenium` y `project_id_solarview` son esquemas de id
    DISTINTOS que no coinciden entre sí -- no se puede derivar uno del otro,
    hace falta este match por nombre igual que el de Solenium.

Formas de uso:
  - `sincronizar_project_id_solarview_si_aplica(proyecto, db)` -- un solo
    proyecto, en el momento de crearlo/confirmarlo (ver app/api/v1/proyectos.py).
  - `backfill_project_id_solarview(db, apply=...)` -- corrida masiva, ver
    scripts/backfill_project_id_solarview.py.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto
from app.services.mgs.solarview_client import SolarViewClient
from app.utils.nombre_matching import mejor_candidato

logger = logging.getLogger(__name__)

UMBRAL_PROJECT_ID_SOLARVIEW = 0.95


def _match_solarview_seguro(proyecto: Proyecto, solarview_projects: list[dict]) -> dict | None:
    candidatos = [(p, [p.get("name")]) for p in solarview_projects if p.get("name")]
    item, score = mejor_candidato(proyecto.nombre_comercial, candidatos)
    return item if item and score >= UMBRAL_PROJECT_ID_SOLARVIEW else None


def backfill_project_id_solarview(db: Session, apply: bool = False) -> dict:
    """Corrida masiva sobre proyectos sin `project_id_solarview`. Ver
    scripts/backfill_project_id_solarview.py para el CLI (dry-run por
    defecto)."""
    candidatos_proyecto = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None), Proyecto.project_id_solarview.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    if not candidatos_proyecto:
        return {"ok": True, "revisados": 0, "asignados": [], "sin_match_seguro": []}

    client = SolarViewClient()
    if not client.enabled:
        return {"ok": False, "error": "Credenciales de SolarView no configuradas."}
    try:
        solarview_projects = client.get_company_projects()
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo listar proyectos de SolarView: {exc}"}
    if not solarview_projects:
        return {"ok": False, "error": "SolarView no devolvió proyectos"}

    # project_id_solarview es UNIQUE -- si dos filas de nuestra BD matchean al
    # mismo proyecto de SolarView, solo la primera se queda con el vínculo.
    usados_solarview_id = {
        v for v in (
            row[0] for row in db.query(Proyecto.project_id_solarview)
            .filter(Proyecto.deleted_at.is_(None), Proyecto.project_id_solarview.isnot(None))
            .all()
        )
    }

    asignados: list[dict] = []
    sin_match_seguro: list[dict] = []

    for p in candidatos_proyecto:
        item = _match_solarview_seguro(p, solarview_projects)
        if not item:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": "sin match seguro en SolarView",
            })
            continue

        nuevo_id = str(item["id"])
        if nuevo_id in usados_solarview_id:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": f"matcheó con SolarView id={nuevo_id}, pero ya está tomado por otro proyecto en esta corrida",
            })
            continue

        asignados.append({
            "proyecto_id": p.id, "nombre": p.nombre_comercial,
            "cambios": {"proyecto.project_id_solarview": nuevo_id},
        })
        usados_solarview_id.add(nuevo_id)
        if apply:
            p.project_id_solarview = nuevo_id

    if apply and asignados:
        db.commit()

    return {
        "ok": True,
        "revisados": len(candidatos_proyecto),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def sincronizar_project_id_solarview_si_aplica(proyecto: Proyecto, db: Session) -> str | None:
    """Best-effort para UN proyecto, en el momento de crearlo/confirmarlo (ver
    app/api/v1/proyectos.py). Nunca sobreescribe, y nunca lanza."""
    if proyecto.project_id_solarview:
        return None
    try:
        client = SolarViewClient()
        if not client.enabled:
            return None
        solarview_projects = client.get_company_projects()
        if not solarview_projects:
            return None
        item = _match_solarview_seguro(proyecto, solarview_projects)
        if not item:
            return None
        nuevo_id = str(item["id"])
        conflicto = db.query(Proyecto).filter(
            Proyecto.project_id_solarview == nuevo_id, Proyecto.id != proyecto.id,
        ).first()
        if conflicto:
            return None
        proyecto.project_id_solarview = nuevo_id
        db.commit()
        return nuevo_id
    except Exception:
        db.rollback()
        logger.warning(
            "No se pudo sincronizar project_id_solarview para proyecto %s (%s)",
            proyecto.id, proyecto.nombre_comercial, exc_info=True,
        )
        return None
