"""
CRUD y flujo de aprobación de informes generados en el módulo de monitoreo.

Endpoints:
  POST   /api/v1/informes/              — crear o actualizar (upsert por tipo+sub_project+periodo)
  GET    /api/v1/informes/              — listar (filtros opcionales)
  GET    /api/v1/informes/{id}          — detalle
  PATCH  /api/v1/informes/{id}/estado   — cambiar estado (revisado / aprobado)
  POST   /api/v1/informes/{id}/enviar   — enviar por email al correo_operacional del cliente
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.informes import InformeGuardado
from app.models.usuarios import Usuario

router = APIRouter(prefix="/api/v1/informes", tags=["informes"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class InformeUpsertIn(BaseModel):
    tipo: str                              # "op" | "fmo" | "port"
    sub_project: str
    periodo_desde: str                     # YYYY-MM-DD
    periodo_hasta: str                     # YYYY-MM-DD
    periodo_display: Optional[str] = None
    proyecto_nombre: Optional[str] = None
    html_content: str
    charts_data: Optional[str] = None     # JSON string del rptChartQueue


class EstadoIn(BaseModel):
    estado: str   # "revisado" | "aprobado"


class InformeOut(BaseModel):
    id: int
    tipo: str
    sub_project: str
    periodo_desde: str
    periodo_hasta: str
    periodo_display: Optional[str]
    proyecto_nombre: Optional[str]
    estado: str
    creado_por_nombre: Optional[str]
    editado_por_nombre: Optional[str]
    aprobado_por_nombre: Optional[str]
    creado_en: datetime
    editado_en: Optional[datetime]
    aprobado_en: Optional[datetime]
    correo_enviado: bool
    correo_enviado_en: Optional[datetime]

    class Config:
        from_attributes = True


class InformeDetailOut(InformeOut):
    html_content: str
    charts_data: Optional[str]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_correo_operacional(db: Session, sub_project: str) -> Optional[str]:
    """Busca el correo_operacional del cliente asociado al proyecto."""
    row = db.execute(
        text("""
            SELECT c.correo_operacional
            FROM proyectos p
            JOIN clientes c ON c.id = p.cliente_id
            WHERE p.sub_project = :sp
               OR p.nombre_comercial = :sp
               OR p.alias_monitoreo ILIKE :sp_like
            LIMIT 1
        """),
        {"sp": sub_project, "sp_like": f"%{sub_project}%"},
    ).fetchone()
    if row and row[0]:
        return row[0]
    return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=InformeDetailOut, summary="Crear o actualizar informe guardado")
def upsert_informe(
    payload: InformeUpsertIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Upsert por (tipo, sub_project, periodo_desde, periodo_hasta)."""
    existing = (
        db.query(InformeGuardado)
        .filter_by(
            tipo=payload.tipo,
            sub_project=payload.sub_project,
            periodo_desde=payload.periodo_desde,
            periodo_hasta=payload.periodo_hasta,
        )
        .first()
    )

    now = datetime.now(timezone.utc)

    if existing:
        # Actualizar — solo borrador o revisado son editables
        if existing.estado == "aprobado":
            raise HTTPException(400, "No se puede editar un informe ya aprobado")
        existing.html_content = payload.html_content
        existing.charts_data = payload.charts_data
        if payload.proyecto_nombre:
            existing.proyecto_nombre = payload.proyecto_nombre
        if payload.periodo_display:
            existing.periodo_display = payload.periodo_display
        existing.editado_por_id = current_user.id
        existing.editado_por_nombre = current_user.nombre
        existing.editado_en = now
        db.commit()
        db.refresh(existing)
        return existing
    else:
        nuevo = InformeGuardado(
            tipo=payload.tipo,
            sub_project=payload.sub_project,
            periodo_desde=payload.periodo_desde,
            periodo_hasta=payload.periodo_hasta,
            periodo_display=payload.periodo_display,
            proyecto_nombre=payload.proyecto_nombre,
            html_content=payload.html_content,
            charts_data=payload.charts_data,
            estado="borrador",
            creado_por_id=current_user.id,
            creado_por_nombre=current_user.nombre,
            editado_por_id=current_user.id,
            editado_por_nombre=current_user.nombre,
            editado_en=now,
        )
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return nuevo


@router.get("/", response_model=list[InformeOut], summary="Listar informes guardados")
def list_informes(
    tipo: Optional[str] = Query(None),
    sub_project: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q = db.query(InformeGuardado)
    if tipo:
        q = q.filter(InformeGuardado.tipo == tipo)
    if sub_project:
        q = q.filter(InformeGuardado.sub_project == sub_project)
    if estado:
        q = q.filter(InformeGuardado.estado == estado)
    return q.order_by(InformeGuardado.editado_en.desc().nullslast()).limit(limit).all()


@router.get("/{informe_id}", response_model=InformeDetailOut, summary="Detalle de informe")
def get_informe(
    informe_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    return inf


@router.patch("/{informe_id}/estado", response_model=InformeOut, summary="Cambiar estado del informe")
def change_estado(
    informe_id: int,
    payload: EstadoIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")

    allowed = {"borrador": ["revisado"], "revisado": ["aprobado", "borrador"]}
    if payload.estado not in allowed.get(inf.estado, []):
        raise HTTPException(400, f"Transición inválida: {inf.estado} → {payload.estado}")

    now = datetime.now(timezone.utc)
    inf.estado = payload.estado

    if payload.estado == "aprobado":
        inf.aprobado_por_id = current_user.id
        inf.aprobado_por_nombre = current_user.nombre
        inf.aprobado_en = now
    elif payload.estado == "revisado":
        # quien marcó revisado = editor
        inf.editado_por_id = current_user.id
        inf.editado_por_nombre = current_user.nombre
        inf.editado_en = now

    db.commit()
    db.refresh(inf)
    return inf


@router.post("/{informe_id}/enviar", summary="Enviar informe aprobado por email")
def enviar_informe(
    informe_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    if inf.estado != "aprobado":
        raise HTTPException(400, "Solo se pueden enviar informes aprobados")

    correo = _get_correo_operacional(db, inf.sub_project)
    if not correo:
        raise HTTPException(
            422,
            "No se encontró correo_operacional para este proyecto. "
            "Configúralo en la ficha del cliente.",
        )

    try:
        from app.services.email_service import send_informe_email
        send_informe_email(
            to_email=correo,
            proyecto_nombre=inf.proyecto_nombre or inf.sub_project,
            periodo_display=inf.periodo_display or f"{inf.periodo_desde} — {inf.periodo_hasta}",
            aprobado_por=inf.aprobado_por_nombre or current_user.nombre,
            html_content=inf.html_content,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Error al enviar email: {exc}") from exc

    inf.correo_enviado = True
    inf.correo_enviado_en = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "enviado_a": correo}
