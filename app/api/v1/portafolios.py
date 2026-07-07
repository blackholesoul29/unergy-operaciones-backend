"""
Gestión de portafolios (capas de proyectos).

Un portafolio agrupa proyectos vía proyectos.portafolio_id. Es la fuente de verdad
del agrupamiento usado por los informes ('Por portafolio'). Se siembra una vez desde
el agrupamiento por cliente/inversionista para no perder la relación existente; de ahí
en más se gestiona manualmente (drag-and-drop en el frontend).

Endpoints:
  GET    /api/v1/portafolios              — capas con sus proyectos + pool 'sin portafolio'
  POST   /api/v1/portafolios              — crear capa
  PATCH  /api/v1/portafolios/{id}         — renombrar / descripción / activo
  DELETE /api/v1/portafolios/{id}         — eliminar capa (sus proyectos quedan sin portafolio)
  PATCH  /api/v1/portafolios/asignar      — asignar/desasignar un proyecto a una capa
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Proyecto
from app.models.proyectos import Portafolio, ProyectoInversionista

router = APIRouter(prefix="/portafolios", tags=["Portafolios"])


# ── Schemas ─────────────────────────────────────────────────────────────────
class PortafolioCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None


class PortafolioUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    activo: Optional[bool] = None


class AsignarIn(BaseModel):
    proyecto_id: int
    portafolio_id: Optional[int] = None   # null = quitar de su portafolio (queda "sin portafolio")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _es_operativo(p: Proyecto) -> bool:
    return bool(p.srv_operacion) or p.estado == "en_operacion"


def _operativo_filter():
    return or_(Proyecto.srv_operacion == True, Proyecto.estado == "en_operacion")  # noqa: E712


def _seed_portafolios_if_empty(db: Session) -> None:
    """Si todavía no hay portafolios, los crea desde el agrupamiento actual por
    el primer inversionista de cada proyecto y asigna portafolio_id. Idempotente:
    sólo corre cuando la tabla está vacía, así no pisa asignaciones manuales
    posteriores."""
    if db.query(Portafolio).count() > 0:
        return
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None), _operativo_filter())
        .options(
            selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente),
        )
        .all()
    )
    cache: dict[str, Portafolio] = {}
    for p in proyectos:
        if p.portafolio_id:
            continue
        nombre = None
        for inv in (p.inversionistas or []):
            if inv.cliente and inv.cliente.razon_social_nombre:
                nombre = inv.cliente.razon_social_nombre
                break
        if not nombre:
            continue
        port = cache.get(nombre)
        if port is None:
            port = db.query(Portafolio).filter_by(nombre=nombre).first()
            if port is None:
                port = Portafolio(nombre=nombre)
                db.add(port)
                db.flush()
            cache[nombre] = port
        p.portafolio_id = port.id
    db.commit()


def get_portfolios_grouping(db: Session) -> dict:
    """Agrupamiento {nombre_portafolio: [nombre_comercial, ...]} para el wizard de informes.
    Siembra si está vacío y agrupa los proyectos operativos por su portafolio activo."""
    _seed_portafolios_if_empty(db)
    rows = (
        db.query(Proyecto)
        .join(Portafolio, Proyecto.portafolio_id == Portafolio.id)
        .filter(Proyecto.deleted_at.is_(None), Portafolio.activo == True, _operativo_filter())  # noqa: E712
        .options(selectinload(Proyecto.portafolio))
        .all()
    )
    out: dict = {}
    for p in rows:
        nombre = p.portafolio.nombre
        out.setdefault(nombre, [])
        if p.nombre_comercial not in out[nombre]:
            out[nombre].append(p.nombre_comercial)
    return out


def _proj_item(p: Proyecto) -> dict:
    return {
        "id": p.id,
        "nombre": p.nombre_comercial,
        "sub_project": p.sub_project,
        "municipio": p.municipio,
    }


def _port_out(pt: Portafolio, proyectos: list[dict]) -> dict:
    return {
        "id": pt.id,
        "nombre": pt.nombre,
        "descripcion": pt.descripcion,
        "activo": pt.activo,
        "proyectos": proyectos,
    }


# ── Endpoints ───────────────────────────────────────────────────────────────
@router.get("", summary="Capas (portafolios) con sus proyectos + pool sin portafolio")
def list_portafolios(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _seed_portafolios_if_empty(db)
    ports = db.query(Portafolio).order_by(Portafolio.nombre).all()
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    by_port: dict[int, list] = {}
    sin: list = []
    for p in proyectos:
        item = _proj_item(p)
        if p.portafolio_id:
            by_port.setdefault(p.portafolio_id, []).append(item)
        elif _es_operativo(p):
            # Sólo proyectos operativos sin portafolio aparecen en el pool (los relevantes a informes)
            sin.append(item)
    return {
        "portafolios": [_port_out(pt, by_port.get(pt.id, [])) for pt in ports],
        "sin_portafolio": sin,
    }


@router.post("", status_code=201, summary="Crear portafolio")
def create_portafolio(payload: PortafolioCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    nombre = (payload.nombre or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre del portafolio no puede estar vacío")
    if db.query(Portafolio).filter(func.lower(Portafolio.nombre) == nombre.lower()).first():
        raise HTTPException(409, f"Ya existe un portafolio llamado '{nombre}'")
    pt = Portafolio(nombre=nombre, descripcion=(payload.descripcion or None))
    db.add(pt)
    db.commit()
    db.refresh(pt)
    return _port_out(pt, [])


@router.patch("/asignar", summary="Asignar/desasignar un proyecto a un portafolio")
def asignar_proyecto(payload: AsignarIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.get(Proyecto, payload.proyecto_id)
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    if payload.portafolio_id is not None and not db.get(Portafolio, payload.portafolio_id):
        raise HTTPException(404, "Portafolio no encontrado")
    p.portafolio_id = payload.portafolio_id
    db.commit()
    return {"ok": True, "proyecto_id": p.id, "portafolio_id": p.portafolio_id}


@router.patch("/{portafolio_id}", summary="Renombrar / actualizar portafolio")
def update_portafolio(portafolio_id: int, payload: PortafolioUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    pt = db.get(Portafolio, portafolio_id)
    if not pt:
        raise HTTPException(404, "Portafolio no encontrado")
    if payload.nombre is not None:
        nombre = payload.nombre.strip()
        if not nombre:
            raise HTTPException(400, "El nombre no puede estar vacío")
        dup = db.query(Portafolio).filter(
            func.lower(Portafolio.nombre) == nombre.lower(), Portafolio.id != portafolio_id
        ).first()
        if dup:
            raise HTTPException(409, f"Ya existe un portafolio llamado '{nombre}'")
        pt.nombre = nombre
    if payload.descripcion is not None:
        pt.descripcion = payload.descripcion or None
    if payload.activo is not None:
        pt.activo = payload.activo
    db.commit()
    db.refresh(pt)
    return _port_out(pt, [])


@router.delete("/{portafolio_id}", status_code=204, summary="Eliminar portafolio (sus proyectos quedan sin portafolio)")
def delete_portafolio(portafolio_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    pt = db.get(Portafolio, portafolio_id)
    if not pt:
        raise HTTPException(404, "Portafolio no encontrado")
    db.query(Proyecto).filter(Proyecto.portafolio_id == portafolio_id).update(
        {Proyecto.portafolio_id: None}, synchronize_session=False
    )
    db.delete(pt)
    db.commit()
