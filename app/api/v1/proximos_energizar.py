"""Proyectos próximos a energizarse — vista respaldada en la BD de operaciones.

El pipeline de TSF (Sun Factory + originabotdb + generación Unergy) ya NO se lee en
vivo aquí: un job lo sincroniza periódicamente hacia la tabla `proyectos`
(ver `app/services/tsf_sync.py`). Este router solo:
  - GET  `/proximos-energizar`        → lee de `proyectos` (pipeline + fechas futuras).
  - POST `/proximos-energizar/sync`   → dispara la sincronización on-demand (force opc.).
  - PATCH `/proximos-energizar/{id}`  → persiste ediciones del operador (marca la
                                        fecha como editada manualmente).

Así la vista vive 100% en la BD (sin localStorage) y los proyectos quedan listos
para relacionarse con contratos PPA y monitorear cumplimiento de energía.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto
from app.services.tsf_sync import (
    _FASE_TO_LABEL, _STATUS_TO_FASE, _pick_energization_milestone, _sunfactory_all_projects,
    _sunfactory_energization, _sunfactory_milestones_raw, _sunfactory_token, sync_tsf_projects,
)

logger = logging.getLogger("proximos_energizar")
router = APIRouter(prefix="/proximos-energizar", tags=["Próximos a energizarse"])

# Auto-reparado: si el DDL de arranque / la migración no crearon las columnas del
# pipeline TSF en la BD (p. ej. el deploy no alcanzó a correrlas), las creamos aquí
# de forma idempotente para que la vista nunca dé 500 por columna inexistente.
_TSF_COLUMNS_DDL = [
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origina_code VARCHAR(100)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fase_construccion VARCHAR(40)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fase_construccion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_estimada_energizacion DATE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_estimada_editada_manual BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS avance_obra_pct NUMERIC(5,2)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS mwh_mes_estimado NUMERIC(12,2)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origen VARCHAR(20) DEFAULT 'manual'",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sunfactory_project_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_origina_code ON proyectos (origina_code) WHERE origina_code IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_proyectos_sunfactory_project_id "
    "ON proyectos (sunfactory_project_id) WHERE sunfactory_project_id IS NOT NULL",
]
_columns_ensured = False


def _ensure_tsf_columns(db: Session) -> None:
    """Crea las columnas del pipeline TSF si faltan (idempotente, 1 vez/proceso)."""
    global _columns_ensured
    if _columns_ensured:
        return
    for stmt in _TSF_COLUMNS_DDL:
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("ensure TSF column falló (%s): %s", stmt[:50], exc)
    _columns_ensured = True


def _contract_names(proyecto: Proyecto) -> list[str]:
    """Nombres de los contratos PPA ligados al proyecto (para la columna Contratos)."""
    names: list[str] = []
    try:
        for c in (proyecto.ppa_contratos or []):
            label = getattr(c, "nombre_interno", None) or getattr(c, "numero_codigo_contrato", None)
            if label:
                names.append(label)
    except Exception:
        pass
    return names


def _serialize(p: Proyecto, frontera: dict | None = None) -> dict:
    """Forma compatible con el frontend (ProyectosProximosEnergizar.vue)."""
    fase = p.fase_construccion
    status = _FASE_TO_LABEL.get(fase) if fase else None
    return {
        "id": p.id,
        "name": p.origina_code or p.codigo_tsf or "",
        "commercialName": p.nombre_comercial,
        "status": status or "En construcción",
        "energizationDate": p.fecha_estimada_energizacion.isoformat() if p.fecha_estimada_energizacion else None,
        "avancePct": float(p.avance_obra_pct) if p.avance_obra_pct is not None else None,
        "monthlyMwh": float(p.mwh_mes_estimado) if p.mwh_mes_estimado is not None else 0,
        "contracts": _contract_names(p),
        "municipio": p.municipio,
        "departamento": p.departamento,
        "origen": p.origen,
        "editadaManual": bool(p.fecha_estimada_editada_manual),
        "estadoEditadoManual": bool(p.fase_construccion_editada_manual),
        # "Frontera asignada" -- pregunta frecuente: qué proyectos en construcción
        # ya tienen frontera comercial registrada (señal real de energización
        # inminente, más confiable que la fase de Sun Factory). Viene de nuestra
        # propia tabla `fronteras`, no de una llamada en vivo a Quoia.
        "tieneFrontera": frontera is not None,
        "codigoFrontera": frontera["codigo_frontera"] if frontera else None,
        # Ya confirmado como operando (vía Proyectos pendientes / frontera con
        # evidencia real), pero Sun Factory todavía no actualizó su fase -- caso
        # real "Galeras": si no se marca aparte, se ve como si siguiera en obra.
        "yaOperando": p.estado == "en_operacion",
    }


def _fronteras_por_proyecto(db: Session, proyecto_ids: list[int]) -> dict[int, dict]:
    """{ proyecto_id: {codigo_frontera} } para la frontera de generación de cada
    proyecto (si tiene varias, se queda con la primera). Une generacion y
    generacion_consumo -- ambas son borders de punto de generación real."""
    if not proyecto_ids:
        return {}
    out: dict[int, dict] = {}
    rows = (
        db.query(Frontera.proyecto_id, Frontera.codigo_frontera)
        .filter(
            Frontera.proyecto_id.in_(proyecto_ids),
            Frontera.tipo_frontera.in_(["generacion", "generacion_consumo"]),
            Frontera.deleted_at.is_(None),
        )
        .all()
    )
    for proyecto_id, codigo in rows:
        out.setdefault(proyecto_id, {"codigo_frontera": codigo})
    return out


@router.get("")
def listar_proximos_energizar(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Proyectos del pipeline TSF (fase activa) + proyectos registrados cuya fecha
    de inicio aún no ha llegado. Todo leído de la BD de operaciones."""
    _ensure_tsf_columns(db)
    today = date.today()
    try:
        rows = (
            db.query(Proyecto)
            .filter(Proyecto.deleted_at.is_(None))
            # Si YA lo tenemos marcado como en operación -- así haya sido por
            # confirmación manual, o vía /proyectos/pendientes con evidencia de
            # Quoia/Solenium -- no debe seguir apareciendo aquí, aunque Sun
            # Factory no se haya actualizado y siga diciendo "en construcción".
            .filter(Proyecto.estado != "en_operacion")
            .filter(
                or_(
                    # Pipeline TSF: en alguna fase de construcción y aún no energizado.
                    and_(
                        Proyecto.fase_construccion.isnot(None),
                        Proyecto.fase_construccion != "energizado",
                    ),
                    # Registrados cuya energización estimada aún no llega.
                    Proyecto.fecha_estimada_energizacion > today,
                )
            )
            .order_by(Proyecto.fecha_estimada_energizacion.asc().nullslast())
            .all()
        )

        # Caso real "Galeras": ya opera (estado='en_operacion', normalmente
        # confirmado por tener frontera con evidencia real) pero Sun Factory
        # todavía no actualizó su fase de obra. Se listan aparte -- no porque
        # sigan en el pipeline de construcción, sino para que el desfase entre
        # `estado` y `fase_construccion` no pase desapercibido.
        desfasados = (
            db.query(Proyecto)
            .filter(Proyecto.deleted_at.is_(None))
            .filter(Proyecto.estado == "en_operacion")
            .filter(Proyecto.fase_construccion.isnot(None), Proyecto.fase_construccion != "energizado")
            .order_by(Proyecto.nombre_comercial.asc())
            .all()
        )
    except Exception as exc:
        # Nunca tumbar la vista por un problema de esquema/consulta: degradar.
        db.rollback()
        logger.warning("listar_proximos_energizar falló: %s", exc)
        return {"projects": [], "source": "error", "count": 0,
                "warning": "No se pudo cargar la lista. Intenta «Sincronizar ahora» "
                           "para poblar el pipeline desde Solenium/TSF."}
    rows = desfasados + rows
    fronteras = _fronteras_por_proyecto(db, [p.id for p in rows])
    return {
        "projects": [_serialize(p, fronteras.get(p.id)) for p in rows],
        "source": "operaciones_db",
        "count": len(rows),
    }


@router.post("/sync")
def sincronizar(
    force: bool = Query(False, description="Sobrescribe las fechas editadas manualmente con la info de Solenium."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Dispara la sincronización TSF → proyectos on-demand (botones de la vista).

    On-demand corre con `enrich_dates=False` (rápido: solo el listado de Sun Factory
    + upserts, sin las ~99 llamadas de hitos que harían timeout el request). El job
    programado de 6h trae luego la fecha de energización precisa (RETIE)."""
    _ensure_tsf_columns(db)
    try:
        stats = sync_tsf_projects(db, force=force, enrich_dates=False)
    except Exception as exc:
        logger.warning("sync TSF falló: %s", exc)
        raise HTTPException(status_code=502,
                            detail=f"No se pudo sincronizar con Solenium/TSF: {exc}")
    return stats


class ProximoEnergizarPatch(BaseModel):
    commercialName: str | None = None
    energizationDate: date | None = None
    monthlyMwh: float | None = None
    status: str | None = None  # etiqueta ('Próximo a energizar') o slug ('proximo_energizar')


@router.patch("/{proyecto_id}")
def actualizar(
    proyecto_id: int,
    body: ProximoEnergizarPatch,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Persiste ediciones inline del operador. Cambiar la fecha la marca como
    editada manualmente, para que el sync periódico no la pise (salvo force)."""
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if body.commercialName is not None:
        p.nombre_comercial = body.commercialName
    if body.monthlyMwh is not None:
        p.mwh_mes_estimado = body.monthlyMwh
    if body.status is not None:
        # Acepta etiqueta o slug; normaliza a slug.
        nueva_fase = _STATUS_TO_FASE.get(body.status, body.status)
        if nueva_fase != p.fase_construccion:
            p.fase_construccion = nueva_fase
            p.fase_construccion_editada_manual = True
    if body.energizationDate is not None and body.energizationDate != p.fecha_estimada_energizacion:
        p.fecha_estimada_energizacion = body.energizationDate
        p.fecha_estimada_editada_manual = True

    db.commit()
    db.refresh(p)
    return _serialize(p, _fronteras_por_proyecto(db, [p.id]).get(p.id))


@router.post("/{proyecto_id}/restaurar-fecha")
def restaurar_fecha(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Descarta la fecha editada a mano de ESTE proyecto y trae de nuevo la de
    Sun Factory. Reemplaza al botón global de "forzar sobrescritura": más
    seguro (un proyecto a la vez, con el operador viendo cuál) y más
    descubrible (vive junto al ícono que ya marca "editada manualmente")."""
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if not p.sunfactory_project_id:
        raise HTTPException(status_code=400,
                             detail="Este proyecto no tiene vínculo con Sun Factory -- no hay fecha automática que restaurar.")

    token = _sunfactory_token()
    if not token:
        raise HTTPException(status_code=502, detail="Credenciales de Sun Factory no configuradas.")
    try:
        energ = _sunfactory_energization(token, p.sunfactory_project_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Sun Factory: {exc}")
    if not energ or not energ.get("energization_date"):
        raise HTTPException(status_code=404, detail="Sun Factory no tiene una fecha de energización para este proyecto todavía.")

    p.fecha_estimada_energizacion = energ["energization_date"]
    p.fecha_estimada_editada_manual = False
    if energ.get("avance_pct") is not None:
        p.avance_obra_pct = energ["avance_pct"]
    db.commit()
    db.refresh(p)
    return _serialize(p, _fronteras_por_proyecto(db, [p.id]).get(p.id))


@router.get("/{proyecto_id}/debug-sunfactory")
def debug_sunfactory(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """Diagnóstico de solo lectura: qué trae Sun Factory CRUDO para este proyecto
    (milestones sin filtrar + el registro del listado con su `next_milestone`).
    Sirve para responder "¿por qué no tiene fecha/avance?" sin adivinar -- muestra
    si Sun Factory de verdad no tiene el dato, o si simplemente el botón on-demand
    (que no consulta milestones) no lo ha traído todavía."""
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if not p.sunfactory_project_id:
        return {"vinculado": False, "detalle": "Este proyecto no tiene sunfactory_project_id."}

    token = _sunfactory_token()
    if not token:
        raise HTTPException(status_code=502, detail="Credenciales de Sun Factory no configuradas.")

    try:
        milestones = _sunfactory_milestones_raw(token, p.sunfactory_project_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar milestones: {exc}")
    elegido = _pick_energization_milestone(milestones)

    listado = next(
        (row for row in _sunfactory_all_projects(token) if row.get("id") == p.sunfactory_project_id),
        None,
    )

    return {
        "vinculado": True,
        "sunfactory_project_id": p.sunfactory_project_id,
        "fecha_actual_bd": p.fecha_estimada_energizacion.isoformat() if p.fecha_estimada_energizacion else None,
        "editada_manual": bool(p.fecha_estimada_editada_manual),
        "milestones_total": len(milestones),
        "milestones_con_fecha": [
            {"name": m.get("name"), "date": m.get("date"), "planned_date": m.get("planned_date")}
            for m in milestones if m.get("date") or m.get("planned_date")
        ],
        "milestone_energizacion_elegido": elegido,
        "sunfactory_state": listado.get("state") if listado else None,
        "next_milestone_del_listado": listado.get("next_milestone") if listado else None,
    }
