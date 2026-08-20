"""Backfill de datos técnicos (`ProyectoInfoTecnica` + `Proyecto.operador_red`/
`potencia_instalada_kwp`) desde `SoleniumClient.get_project_detail()`.

Probado en vivo (2026-08-11): ese endpoint solo trae datos reales (no
"Desconocida") para proyectos tipo minigranja -- para el resto (autoconsumo/
GD/comercial) Solenium no tiene esta info diligenciada, así que no hay nada
que backfillear ahí.

Mismo criterio que el resto de backfills de esta sesión (Unergy, Sun Factory):
  - Si el proyecto ya tiene `project_id_solenium`, se usa ese vínculo directo
    (sin ambigüedad).
  - Si no, se empareja por nombre contra el listado de Solenium
    (`mejor_candidato`, umbral 0.95) -- y de paso se asigna `project_id_solenium`
    si el match es seguro, para no tener que volver a adivinar la próxima vez.
  - Nunca sobreescribe un valor ya cargado.

Formas de uso:
  - `sincronizar_info_tecnica_solenium_si_aplica(proyecto, db)` -- un solo
    proyecto, en el momento de crearlo/confirmarlo (ver app/api/v1/proyectos.py).
  - `backfill_info_tecnica_solenium(db, apply=...)` -- corrida masiva, ver
    scripts/backfill_info_tecnica_solenium.py.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto, ProyectoInfoTecnica
from app.services.mgs.solenium_client import SoleniumClient
from app.utils.nombre_matching import mejor_candidato

logger = logging.getLogger(__name__)

UMBRAL_INFO_TECNICA_SOLENIUM = 0.95

# Solenium usa este texto como placeholder de "sin dato" -- no es un valor real.
_SIN_DATO = "Desconocida"


def _num(v) -> float | None:
    if v is None or v == _SIN_DATO:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _texto(v) -> str | None:
    if v is None or v == _SIN_DATO:
        return None
    return str(v)


def _match_solenium_por_id(proyecto: Proyecto, solenium_projects: list[dict]) -> dict | None:
    if not proyecto.project_id_solenium:
        return None
    try:
        pid = int(proyecto.project_id_solenium)
    except (TypeError, ValueError):
        return None
    return next((p for p in solenium_projects if p.get("id") == pid), None)


def _match_solenium_seguro(proyecto: Proyecto, solenium_projects: list[dict]) -> dict | None:
    item = _match_solenium_por_id(proyecto, solenium_projects)
    if item:
        return item
    candidatos = [(p, [p.get("name")]) for p in solenium_projects if p.get("name")]
    item, score = mejor_candidato(proyecto.nombre_comercial, candidatos)
    return item if item and score >= UMBRAL_INFO_TECNICA_SOLENIUM else None


def _cambios_info_tecnica(proyecto: Proyecto, it: ProyectoInfoTecnica, detalle: dict) -> dict:
    """Solo los campos vacíos -- nunca pisa un valor ya cargado. `detalle` es
    la respuesta de get_project_detail()['results']."""
    cambios: dict = {}

    capacidad = _num(detalle.get("installed_capacity"))
    if capacidad is not None:
        if it.capacidad_instalada_kwp is None:
            cambios["info_tecnica.capacidad_instalada_kwp"] = capacidad
        if proyecto.potencia_instalada_kwp is None:
            cambios["proyecto.potencia_instalada_kwp"] = capacidad

    voltaje = _texto(detalle.get("grid_voltage"))
    if voltaje is not None and it.voltaje_red is None:
        cambios["info_tecnica.voltaje_red"] = voltaje

    operador = _texto(detalle.get("grid_operator"))
    if operador is not None and not proyecto.operador_red:
        cambios["proyecto.operador_red"] = operador

    paneles = detalle.get("panel_quantity")
    paneles = int(paneles) if isinstance(paneles, (int, float)) or (isinstance(paneles, str) and paneles.isdigit()) else None
    if paneles is not None and it.cantidad_total_paneles is None:
        cambios["info_tecnica.cantidad_total_paneles"] = paneles

    potencia_panel = _texto(detalle.get("panel_power"))
    if potencia_panel is not None and it.potencia_panel_kwp is None:
        cambios["info_tecnica.potencia_panel_kwp"] = potencia_panel

    potencia_inv = _texto(detalle.get("inverter_power"))
    if potencia_inv is not None and it.potencia_inversores_kwp is None:
        cambios["info_tecnica.potencia_inversores_kwp"] = potencia_inv

    cant_inv = detalle.get("inverter_quantity")
    cant_inv = int(cant_inv) if isinstance(cant_inv, (int, float)) or (isinstance(cant_inv, str) and cant_inv.isdigit()) else None
    if cant_inv is not None and it.cantidad_inversores is None:
        cambios["info_tecnica.cantidad_inversores"] = cant_inv

    return cambios


def _aplicar_cambios(proyecto: Proyecto, it: ProyectoInfoTecnica, cambios: dict) -> None:
    for clave, valor in cambios.items():
        objeto, campo = clave.split(".", 1)
        setattr(it if objeto == "info_tecnica" else proyecto, campo, valor)


def backfill_info_tecnica_solenium(db: Session, apply: bool = False) -> dict:
    """Corrida masiva sobre proyectos existentes a los que les falte
    capacidad_instalada_kwp (como proxy de "sin info técnica de Solenium").
    Ver scripts/backfill_info_tecnica_solenium.py para el CLI (dry-run por
    defecto)."""
    candidatos_proyecto = (
        db.query(Proyecto)
        .outerjoin(ProyectoInfoTecnica, ProyectoInfoTecnica.proyecto_id == Proyecto.id)
        .filter(
            Proyecto.deleted_at.is_(None),
            (ProyectoInfoTecnica.capacidad_instalada_kwp.is_(None)) | (ProyectoInfoTecnica.id.is_(None)),
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    if not candidatos_proyecto:
        return {"ok": True, "revisados": 0, "asignados": [], "sin_match_seguro": []}

    client = SoleniumClient()
    if not client.enabled:
        return {"ok": False, "error": "Credenciales de Solenium no configuradas."}
    try:
        solenium_projects = client.get_projects()
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo listar proyectos de Solenium: {exc}"}
    if not solenium_projects:
        return {"ok": False, "error": "Solenium no devolvió proyectos"}

    # project_id_solenium es UNIQUE -- si dos filas de nuestra BD (ej. un
    # duplicado real, se han visto casos) matchean al mismo proyecto de
    # Solenium, solo la primera se queda con el vínculo.
    usados_solenium_id = {
        v for v in (
            row[0] for row in db.query(Proyecto.project_id_solenium)
            .filter(Proyecto.deleted_at.is_(None), Proyecto.project_id_solenium.isnot(None))
            .all()
        )
    }

    asignados: list[dict] = []
    sin_match_seguro: list[dict] = []

    for p in candidatos_proyecto:
        item = _match_solenium_seguro(p, solenium_projects)
        if not item:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": "sin match seguro en Solenium",
            })
            continue

        try:
            detalle_resp = client.get_project_detail(item["id"])
        except Exception as exc:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": f"matcheó pero get_project_detail falló: {exc}",
            })
            continue
        detalle = (detalle_resp or {}).get("results") or {}

        it = p.info_tecnica or ProyectoInfoTecnica(proyecto_id=p.id)
        cambios = _cambios_info_tecnica(p, it, detalle)

        # Vincular project_id_solenium de paso, si no lo tenía y nadie más lo
        # reclamó ya en esta misma corrida -- evita re-adivinar por nombre la
        # próxima vez.
        nuevo_id = str(item["id"])
        if not p.project_id_solenium and nuevo_id not in usados_solenium_id:
            cambios["proyecto.project_id_solenium"] = nuevo_id
            usados_solenium_id.add(nuevo_id)

        if not cambios:
            sin_match_seguro.append({
                "proyecto_id": p.id, "nombre": p.nombre_comercial,
                "motivo": "matcheó con Solenium, pero ese proyecto tampoco tiene datos técnicos diligenciados",
            })
            continue

        asignados.append({"proyecto_id": p.id, "nombre": p.nombre_comercial, "cambios": cambios})
        if apply:
            if it.id is None:
                db.add(it)
            _aplicar_cambios(p, it, cambios)

    if apply and asignados:
        db.commit()

    return {
        "ok": True,
        "revisados": len(candidatos_proyecto),
        "asignados": asignados,
        "sin_match_seguro": sin_match_seguro,
    }


def sincronizar_info_tecnica_solenium_si_aplica(proyecto: Proyecto, db: Session) -> dict | None:
    """Best-effort para UN proyecto, en el momento de crearlo/confirmarlo (ver
    app/api/v1/proyectos.py). Nunca sobreescribe, y nunca lanza."""
    it = proyecto.info_tecnica
    if it and it.capacidad_instalada_kwp is not None:
        return None  # ya tiene info técnica de alguna fuente, no hay nada que rellenar
    try:
        client = SoleniumClient()
        if not client.enabled:
            return None
        solenium_projects = client.get_projects()
        if not solenium_projects:
            return None
        item = _match_solenium_seguro(proyecto, solenium_projects)
        if not item:
            return None
        detalle_resp = client.get_project_detail(item["id"])
        detalle = (detalle_resp or {}).get("results") or {}

        if it is None:
            it = ProyectoInfoTecnica(proyecto_id=proyecto.id)
        cambios = _cambios_info_tecnica(proyecto, it, detalle)
        nuevo_id = str(item["id"])
        if not proyecto.project_id_solenium:
            conflicto = db.query(Proyecto).filter(
                Proyecto.project_id_solenium == nuevo_id, Proyecto.id != proyecto.id,
            ).first()
            if not conflicto:
                cambios["proyecto.project_id_solenium"] = nuevo_id
        if not cambios:
            return None
        if it.id is None:
            db.add(it)
        _aplicar_cambios(proyecto, it, cambios)
        db.commit()
        return cambios
    except Exception:
        db.rollback()
        logger.warning(
            "No se pudo sincronizar info técnica de Solenium para proyecto %s (%s)",
            proyecto.id, proyecto.nombre_comercial, exc_info=True,
        )
        return None
