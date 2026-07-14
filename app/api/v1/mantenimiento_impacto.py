"""Endpoints CRUD del módulo de Impacto de Mantenimiento.

Cada creación/actualización recalcula la energía perdida y el impacto económico
vía `ImpactCalculator`, de modo que esos campos siempre reflejan la ventana de
tiempo y la generación esperada/real del evento (no se editan a mano).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.mantenimiento_impacto import MantenimientoImpacto
from app.models.proyectos import Proyecto
from app.schemas.mantenimiento_impacto import (
    MantenimientoImpactoCreate, MantenimientoImpactoUpdate, MantenimientoImpactoResponse,
)
from app.services.impact_calculator import ImpactCalculator

router = APIRouter(prefix="/mantenimiento-impacto", tags=["Mantenimiento Impacto"])


def _to_response(m: MantenimientoImpacto) -> MantenimientoImpactoResponse:
    return MantenimientoImpactoResponse(
        id=m.id,
        proyecto_id=m.proyecto_id,
        proyecto_nombre=m.proyecto.nombre_comercial if m.proyecto else None,
        falla_id=m.falla_id,
        maintenance_type=m.maintenance_type,
        start_time=m.start_time,
        end_time=m.end_time,
        duration_hours=m.duration_hours,
        expected_generation_kwh=float(m.expected_generation_kwh) if m.expected_generation_kwh is not None else None,
        actual_generation_kwh=float(m.actual_generation_kwh) if m.actual_generation_kwh is not None else None,
        lost_energy_kwh=float(m.lost_energy_kwh) if m.lost_energy_kwh is not None else None,
        financial_impact_cop=float(m.financial_impact_cop) if m.financial_impact_cop is not None else None,
        ppa_penalty_risk_flag=m.ppa_penalty_risk_flag,
        created_by=m.created_by,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _apply_metrics(m: MantenimientoImpacto, db: Session) -> None:
    """Recalcula y asigna energía perdida / impacto económico / bandera PPA."""
    metrics = ImpactCalculator(db).calculate_impact(
        proyecto_id=m.proyecto_id,
        start=m.start_time,
        end=m.end_time,
        expected_generation_kwh=(
            float(m.expected_generation_kwh) if m.expected_generation_kwh is not None else None
        ),
        actual_generation_kwh=(
            float(m.actual_generation_kwh) if m.actual_generation_kwh is not None else None
        ),
    )
    m.expected_generation_kwh = metrics["expected_generation_kwh"]
    m.actual_generation_kwh = metrics["actual_generation_kwh"]
    m.lost_energy_kwh = metrics["lost_energy_kwh"]
    m.financial_impact_cop = metrics["financial_impact_cop"]
    m.ppa_penalty_risk_flag = metrics["ppa_penalty_risk_flag"]


@router.get("", response_model=list[MantenimientoImpactoResponse])
def listar(
    proyecto_id: int | None = Query(None),
    maintenance_type: str | None = Query(None),
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(MantenimientoImpacto).options(selectinload(MantenimientoImpacto.proyecto))
    if proyecto_id:
        q = q.filter(MantenimientoImpacto.proyecto_id == proyecto_id)
    if maintenance_type:
        q = q.filter(MantenimientoImpacto.maintenance_type == maintenance_type)
    if fecha_inicio:
        q = q.filter(MantenimientoImpacto.start_time >= fecha_inicio)
    if fecha_fin:
        q = q.filter(MantenimientoImpacto.start_time <= fecha_fin)
    rows = q.order_by(MantenimientoImpacto.start_time.desc()).all()
    return [_to_response(m) for m in rows]


@router.post("", response_model=MantenimientoImpactoResponse, status_code=201)
def crear(
    data: MantenimientoImpactoCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if data.end_time < data.start_time:
        raise HTTPException(400, "end_time no puede ser anterior a start_time")
    if not db.get(Proyecto, data.proyecto_id):
        raise HTTPException(404, f"Proyecto {data.proyecto_id} no encontrado")

    m = MantenimientoImpacto(
        proyecto_id=data.proyecto_id,
        falla_id=data.falla_id,
        maintenance_type=data.maintenance_type,
        start_time=data.start_time,
        end_time=data.end_time,
        expected_generation_kwh=data.expected_generation_kwh,
        actual_generation_kwh=data.actual_generation_kwh,
        created_by=getattr(current_user, "id", None),
    )
    _apply_metrics(m, db)
    db.add(m)
    db.commit()
    db.refresh(m)
    db.refresh(m, ["proyecto"])
    return _to_response(m)


@router.get("/{id}", response_model=MantenimientoImpactoResponse)
def obtener(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    m = (
        db.query(MantenimientoImpacto)
        .options(selectinload(MantenimientoImpacto.proyecto))
        .filter(MantenimientoImpacto.id == id)
        .first()
    )
    if not m:
        raise HTTPException(404, "Registro de impacto no encontrado")
    return _to_response(m)


@router.put("/{id}", response_model=MantenimientoImpactoResponse)
def actualizar(
    id: int,
    data: MantenimientoImpactoUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    m = db.query(MantenimientoImpacto).filter(MantenimientoImpacto.id == id).first()
    if not m:
        raise HTTPException(404, "Registro de impacto no encontrado")

    for field, val in data.model_dump(exclude_unset=True).items():
        setattr(m, field, val)
    if m.end_time < m.start_time:
        raise HTTPException(400, "end_time no puede ser anterior a start_time")

    _apply_metrics(m, db)
    db.commit()
    db.refresh(m)
    db.refresh(m, ["proyecto"])
    return _to_response(m)


@router.delete("/{id}", status_code=204)
def eliminar(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    m = db.query(MantenimientoImpacto).filter(MantenimientoImpacto.id == id).first()
    if not m:
        raise HTTPException(404, "Registro de impacto no encontrado")
    db.delete(m)
    db.commit()
