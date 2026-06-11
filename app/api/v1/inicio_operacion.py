from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.inicio_operacion import ProyectoInicioOperacion
from app.models.proyectos import Proyecto
from app.schemas.inicio_operacion import (
    InicioOperacionDetail, InicioOperacionFicha,
    InicioOperacionListItem, InicioOperacionProyecto,
)

router = APIRouter(prefix="/inicio-operacion", tags=["Inicio de Operación"])

# Claves del checklist (deben coincidir con el catálogo del frontend) para
# calcular el % de avance en la lista de proyectos.
_CHECKLIST_KEYS = [
    "paneles", "inversores", "estacion_meteo", "cctv", "cable_solar",
    "cableado_mt_bt", "transformadores", "rele_reconectador", "tableros",
    "shelter_skid", "tracker", "obras_civiles", "doc_om",
]


def _progreso(checklist: dict | None) -> int:
    total = len(_CHECKLIST_KEYS)
    if not total:
        return 0
    aprobados = sum(1 for k in _CHECKLIST_KEYS if (checklist or {}).get(k) == "aprobado")
    return round(aprobados / total * 100)


def _ficha_de(f: ProyectoInicioOperacion | None, proyecto: Proyecto) -> InicioOperacionFicha:
    return InicioOperacionFicha(
        empresa_contratista=f.empresa_contratista if f else None,
        fecha_energizacion=f.fecha_energizacion if f else None,
        # Por defecto, prellenar inicio de operación con la fecha de entrada del proyecto.
        fecha_inicio_operacion=(f.fecha_inicio_operacion if f else None) or proyecto.fecha_entrada_operacion,
        checklist=(f.checklist if f else {}) or {},
        pruebas=(f.pruebas if f else {}) or {},
        documentos=(f.documentos if f else {}) or {},
        pendientes=(f.pendientes if f else []) or [],
    )


@router.get("/proyectos", response_model=list[InicioOperacionListItem])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Proyectos con servicio de operación, con su % de avance de checklist."""
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.srv_operacion == True, Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    fichas = {f.proyecto_id: f for f in db.query(ProyectoInicioOperacion).all()}
    out = []
    for p in proyectos:
        f = fichas.get(p.id)
        out.append(InicioOperacionListItem(
            id=p.id,
            nombre_comercial=p.nombre_comercial,
            municipio=p.municipio,
            departamento=p.departamento,
            potencia_instalada_kwp=float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
            fecha_entrada_operacion=p.fecha_entrada_operacion,
            tiene_ficha=f is not None,
            progreso_pct=_progreso(f.checklist) if f else 0,
        ))
    return out


@router.get("/{proyecto_id}", response_model=InicioOperacionDetail)
def obtener(proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == proyecto_id).first()
    return InicioOperacionDetail(
        proyecto=InicioOperacionProyecto.model_validate(p),
        ficha=_ficha_de(f, p),
    )


@router.put("/{proyecto_id}", response_model=InicioOperacionDetail)
def guardar(
    proyecto_id: int,
    body: InicioOperacionFicha,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInicioOperacion(proyecto_id=proyecto_id)
        db.add(f)

    f.empresa_contratista = body.empresa_contratista
    f.fecha_energizacion = body.fecha_energizacion
    f.fecha_inicio_operacion = body.fecha_inicio_operacion
    f.checklist = body.checklist or {}
    f.pruebas = body.pruebas or {}
    f.documentos = body.documentos or {}
    f.pendientes = body.pendientes or []

    db.commit()
    db.refresh(f)
    return InicioOperacionDetail(
        proyecto=InicioOperacionProyecto.model_validate(p),
        ficha=_ficha_de(f, p),
    )
