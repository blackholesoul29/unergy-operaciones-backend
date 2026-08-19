"""Proxy a la API de Liquidaciones de Unergy.

El frontend no habla directo con api.unergy.io: las credenciales de la cuenta de
servicio viven solo en el servidor. Estos endpoints cruzan los proyectos de esta
base con su configuración de liquidaciones (códigos SIC/FRT, ac_power y flags).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.proyectos import Proyecto
from app.schemas.liquidaciones_api import ProyectoLiquidacionesOut, ProyectoLiquidacionesUpdate
from app.services import liquidaciones_api
from app.services.liquidaciones_api import LiquidacionesAPIError

router = APIRouter(prefix="/liquidaciones-api", tags=["API Liquidaciones"])


def _por_topico() -> dict[str, dict]:
    """Configuración de la API externa indexada por ``nombre_topico``."""
    return {
        p["nombre_topico"]: p
        for p in liquidaciones_api.listar_proyectos()
        if p.get("nombre_topico")
    }


@router.get("/proyectos", response_model=list[ProyectoLiquidacionesOut])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Proyectos de esta base con su configuración de liquidaciones."""
    try:
        config = _por_topico()
    except LiquidacionesAPIError as exc:
        raise HTTPException(503, str(exc))

    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )

    salida: list[ProyectoLiquidacionesOut] = []
    for proy in proyectos:
        datos = config.get(proy.sub_project or "", {})
        salida.append(
            ProyectoLiquidacionesOut(
                proyecto_id=proy.id,
                nombre_comercial=proy.nombre_comercial,
                tipo_proyecto=proy.tipo_proyecto,
                estado=proy.estado,
                nombre_topico=proy.sub_project,
                en_api=bool(datos),
                **{campo: datos.get(campo) for campo in liquidaciones_api.CAMPOS_PROYECTO},
            )
        )
    return salida


@router.patch("/proyectos/{proyecto_id}", response_model=ProyectoLiquidacionesOut)
def actualizar_proyecto(
    proyecto_id: int,
    data: ProyectoLiquidacionesUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Actualiza en la API externa la configuración de liquidaciones del proyecto."""
    proy = (
        db.query(Proyecto)
        .filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None))
        .first()
    )
    if not proy:
        raise HTTPException(404, "Proyecto no encontrado")
    if not proy.sub_project:
        raise HTTPException(
            400,
            "El proyecto no tiene código base (API ID Unergy) y no se puede "
            "identificar en la API de Liquidaciones.",
        )

    cambios = data.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(400, "No se enviaron campos para actualizar")

    try:
        datos = liquidaciones_api.actualizar_proyecto(proy.sub_project, cambios)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    return ProyectoLiquidacionesOut(
        proyecto_id=proy.id,
        nombre_comercial=proy.nombre_comercial,
        tipo_proyecto=proy.tipo_proyecto,
        estado=proy.estado,
        nombre_topico=proy.sub_project,
        en_api=bool(datos),
        **{campo: datos.get(campo) for campo in liquidaciones_api.CAMPOS_PROYECTO},
    )
