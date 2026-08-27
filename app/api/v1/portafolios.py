"""
Gestión de portafolios (capas de proyectos).

Un portafolio agrupa proyectos vía proyectos.portafolio_id. Es la fuente de verdad
del agrupamiento usado por los informes ('Por portafolio'). Se siembra una vez desde
el agrupamiento por cliente/inversionista para no perder la relación existente; de ahí
en más se gestiona manualmente (drag-and-drop en el frontend).

El matching de nombres (siembra automática Y creación/renombrado manual) usa
el mismo algoritmo de solapamiento de tokens + similitud de texto que
proyectos/tsf_sync (app/utils/nombre_matching.py), no comparación exacta --
"FONSAR S.A.S." y "Fonsar SAS" se reconocen como el mismo cliente.

Endpoints:
  GET    /api/v1/portafolios              — capas con sus proyectos + pool 'sin portafolio'
  POST   /api/v1/portafolios              — crear capa
  PATCH  /api/v1/portafolios/{id}         — renombrar / activo
  DELETE /api/v1/portafolios/{id}         — eliminar capa (sus proyectos quedan sin portafolio)
  PATCH  /api/v1/portafolios/asignar      — asignar/desasignar un proyecto a una capa
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Proyecto
from app.models.proyectos import Portafolio, ProyectoInversionista
from app.utils.nombre_matching import mejor_candidato

router = APIRouter(prefix="/portafolios", tags=["Portafolios"])


# ── Schemas ─────────────────────────────────────────────────────────────────
class PortafolioCreate(BaseModel):
    nombre: str


class PortafolioUpdate(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None


class AsignarIn(BaseModel):
    proyecto_id: int
    portafolio_id: Optional[int] = None   # null = quitar de su portafolio (queda "sin portafolio")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _es_operativo(p: Proyecto) -> bool:
    return bool(p.srv_operacion) or p.estado == "en_operacion"


def _operativo_filter():
    return or_(Proyecto.srv_operacion == True, Proyecto.estado == "en_operacion")  # noqa: E712


def _buscar_portafolio_parecido(db: Session, nombre: str, excluir_id: int | None = None) -> Portafolio | None:
    """Busca un portafolio existente con nombre parecido (mismo algoritmo de
    app/utils/nombre_matching.py usado para proyectos/tsf_sync): normaliza,
    quita sufijos societarios (S.A.S./LTDA/E.S.P.) y compara solapamiento de
    tokens + similitud de texto. Los nombres de portafolio son razones
    sociales de clientes, así que "FONSAR S.A.S." vs "Fonsar SAS" deben
    reconocerse como el mismo, no como dos capas distintas."""
    q = db.query(Portafolio)
    if excluir_id is not None:
        q = q.filter(Portafolio.id != excluir_id)
    candidatos = [(pt, [pt.nombre]) for pt in q.all()]
    item, _score = mejor_candidato(nombre, candidatos)
    return item


def _seed_portafolios_if_empty(db: Session) -> None:
    """Si todavía no hay portafolios, los crea desde el agrupamiento actual por
    el primer inversionista de cada proyecto y asigna portafolio_id. Idempotente:
    sólo corre cuando la tabla está vacía, así no pisa asignaciones manuales
    posteriores.

    Matching por nombre parecido (no exacto): dos proyectos con el mismo
    inversionista pero razón social escrita distinto en `clientes` (tildes,
    "S.A.S." vs "SAS", espacios) no deben terminar en dos portafolios
    separados para el mismo cliente."""
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
    creados: list[Portafolio] = []
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
        candidatos = [(pt, [pt.nombre]) for pt in creados]
        port, _score = mejor_candidato(nombre, candidatos)
        if port is None:
            port = Portafolio(nombre=nombre)
            db.add(port)
            db.flush()
            creados.append(port)
        p.portafolio_id = port.id
    try:
        db.commit()
    except IntegrityError:
        # Condicion de carrera (dos requests casi simultaneas sobre la tabla
        # vacia, cada una viendo count()==0): el UNIQUE en nombre evita el
        # duplicado silencioso, pero sin esto la segunda transaccion
        # reventaba con un IntegrityError crudo en vez de un 409 claro.
        db.rollback()
        raise HTTPException(409, "No se pudo sembrar los portafolios iniciales: otra solicitud ya lo estaba haciendo. Reintenta.")


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
def create_portafolio(
    payload: PortafolioCreate,
    forzar: bool = Query(False, description="true: crear igual aunque exista un portafolio con nombre muy parecido"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    nombre = (payload.nombre or "").strip()
    if not nombre:
        raise HTTPException(400, "El nombre del portafolio no puede estar vacío")
    if not forzar:
        # Un nombre identico puntua 1.0 en el matching difuso (muy por encima
        # del umbral), asi que este aviso ya cubre el caso exacto -- no hace
        # falta un chequeo aparte de "== " insensible a mayusculas. El UNIQUE
        # de la BD sigue como red de seguridad si de todos modos se fuerza.
        parecido = _buscar_portafolio_parecido(db, nombre)
        if parecido:
            # detail estructurado (no un string plano): el frontend lo usa para
            # ofrecer "crear de todos modos" (reintenta con forzar=true), mismo
            # patron que el aviso de nombre parecido al crear un Proyecto.
            raise HTTPException(
                409,
                {
                    "mensaje": f"Ya existe un portafolio con un nombre muy parecido: '{parecido.nombre}'.",
                    "duplicado_nombre": True,
                    "candidato_id": parecido.id,
                    "candidato_nombre": parecido.nombre,
                },
            )
    pt = Portafolio(nombre=nombre)
    db.add(pt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Ya existe un portafolio llamado '{nombre}'")
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
def update_portafolio(
    portafolio_id: int,
    payload: PortafolioUpdate,
    forzar: bool = Query(False, description="true: renombrar igual aunque exista un portafolio con nombre muy parecido"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    pt = db.get(Portafolio, portafolio_id)
    if not pt:
        raise HTTPException(404, "Portafolio no encontrado")
    if payload.nombre is not None:
        nombre = payload.nombre.strip()
        if not nombre:
            raise HTTPException(400, "El nombre no puede estar vacío")
        if not forzar:
            parecido = _buscar_portafolio_parecido(db, nombre, excluir_id=portafolio_id)
            if parecido:
                raise HTTPException(
                    409,
                    {
                        "mensaje": f"Ya existe un portafolio con un nombre muy parecido: '{parecido.nombre}'.",
                        "duplicado_nombre": True,
                        "candidato_id": parecido.id,
                        "candidato_nombre": parecido.nombre,
                    },
                )
        pt.nombre = nombre
    if payload.activo is not None:
        pt.activo = payload.activo
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un portafolio con ese nombre")
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
