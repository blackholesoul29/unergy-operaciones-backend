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
from app.models.proyectos import Proyecto
from app.services.tsf_sync import _FASE_TO_LABEL, _STATUS_TO_FASE, sync_tsf_projects

logger = logging.getLogger("proximos_energizar")
router = APIRouter(prefix="/proximos-energizar", tags=["Próximos a energizarse"])

# Auto-reparado: si el DDL de arranque / la migración no crearon las columnas del
# pipeline TSF en la BD (p. ej. el deploy no alcanzó a correrlas), las creamos aquí
# de forma idempotente para que la vista nunca dé 500 por columna inexistente.
_TSF_COLUMNS_DDL = [
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origina_code VARCHAR(100)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fase_construccion VARCHAR(40)",
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


def _serialize(p: Proyecto) -> dict:
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
    }


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
    except Exception as exc:
        # Nunca tumbar la vista por un problema de esquema/consulta: degradar.
        db.rollback()
        logger.warning("listar_proximos_energizar falló: %s", exc)
        return {"projects": [], "source": "error", "count": 0,
                "warning": "No se pudo cargar la lista. Intenta «Sincronizar ahora» "
                           "para poblar el pipeline desde Solenium/TSF."}
    return {"projects": [_serialize(p) for p in rows], "source": "operaciones_db", "count": len(rows)}


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
        p.fase_construccion = _STATUS_TO_FASE.get(body.status, body.status)
    if body.energizationDate is not None and body.energizationDate != p.fecha_estimada_energizacion:
        p.fecha_estimada_energizacion = body.energizationDate
        p.fecha_estimada_editada_manual = True

    db.commit()
    db.refresh(p)
    return _serialize(p)
