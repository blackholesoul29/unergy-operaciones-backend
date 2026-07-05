"""Endpoints de gestión de configuración operativa.

CRUD sobre `configuracion_operativa`: parámetros (precio de energía, factor de
capacidad solar) definibles por proyecto o de forma global. La creación y
modificación requieren rol admin; el listado está disponible para cualquier
usuario autenticado. DELETE es lógico (activo=False), no borra la fila, para
conservar el histórico de valores.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.v1.auth import get_current_user, _require_admin
from app.core.database import get_db
from app.models.configuracion_operativa import ConfiguracionOperativa
from app.models.proyectos import Proyecto
from app.schemas.configuracion_operativa import (
    ConfiguracionOperativaCreate,
    ConfiguracionOperativaUpdate,
    ConfiguracionOperativaResponse,
)

router = APIRouter(prefix="/configuracion", tags=["Configuración"])


def _to_out(c: ConfiguracionOperativa) -> ConfiguracionOperativaResponse:
    return ConfiguracionOperativaResponse(
        id=c.id,
        proyecto_id=c.proyecto_id,
        proyecto_nombre=c.proyecto.nombre_comercial if c.proyecto else None,
        tipo_parametro=c.tipo_parametro,
        valor_float=float(c.valor_float),
        unidad=c.unidad,
        fecha_inicio=c.fecha_inicio,
        fecha_fin=c.fecha_fin,
        activo=c.activo,
    )


@router.get("", response_model=list[ConfiguracionOperativaResponse])
def listar(
    proyecto_id: int | None = Query(None),
    tipo_parametro: str | None = Query(None),
    solo_activos: bool = Query(False),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(ConfiguracionOperativa).options(
        selectinload(ConfiguracionOperativa.proyecto)
    )
    if proyecto_id is not None:
        q = q.filter(ConfiguracionOperativa.proyecto_id == proyecto_id)
    if tipo_parametro:
        q = q.filter(ConfiguracionOperativa.tipo_parametro == tipo_parametro)
    if solo_activos:
        q = q.filter(ConfiguracionOperativa.activo.is_(True))
    rows = q.order_by(
        ConfiguracionOperativa.tipo_parametro,
        ConfiguracionOperativa.fecha_inicio.desc(),
    ).all()
    return [_to_out(c) for c in rows]


@router.post("", response_model=ConfiguracionOperativaResponse, status_code=201)
def crear(
    body: ConfiguracionOperativaCreate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    if body.proyecto_id is not None:
        proyecto = db.get(Proyecto, body.proyecto_id)
        if proyecto is None:
            raise HTTPException(404, "Proyecto no encontrado")

    data = body.model_dump(exclude_unset=True)
    data["tipo_parametro"] = body.tipo_parametro.value
    if not data.get("fecha_inicio"):
        data["fecha_inicio"] = datetime.now(timezone.utc)

    cfg = ConfiguracionOperativa(**data)
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    db.refresh(cfg, ["proyecto"])
    return _to_out(cfg)


@router.get("/{id}", response_model=ConfiguracionOperativaResponse)
def obtener(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    c = (
        db.query(ConfiguracionOperativa)
        .options(selectinload(ConfiguracionOperativa.proyecto))
        .filter(ConfiguracionOperativa.id == id)
        .first()
    )
    if not c:
        raise HTTPException(404, "Configuración no encontrada")
    return _to_out(c)


@router.put("/{id}", response_model=ConfiguracionOperativaResponse)
def actualizar(
    id: int,
    body: ConfiguracionOperativaUpdate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    c = db.query(ConfiguracionOperativa).filter(ConfiguracionOperativa.id == id).first()
    if not c:
        raise HTTPException(404, "Configuración no encontrada")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(c, field, val)
    db.commit()
    db.refresh(c)
    db.refresh(c, ["proyecto"])
    return _to_out(c)


@router.delete("/{id}", status_code=204)
def desactivar(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    """Baja lógica: marca la configuración como inactiva (conserva el histórico)."""
    c = db.query(ConfiguracionOperativa).filter(ConfiguracionOperativa.id == id).first()
    if not c:
        raise HTTPException(404, "Configuración no encontrada")
    c.activo = False
    db.commit()
