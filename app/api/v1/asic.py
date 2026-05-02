from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import AsicSolicitud
from app.models.asic import AsicCambioContrato, GesconDiccionario
from app.schemas.asic import AsicSolicitudOut, AsicSolicitudCreate, AsicCambioCreate, AsicCambioOut, GesconDiccionarioCreate, GesconDiccionarioOut

router = APIRouter(prefix="/asic", tags=["ASIC"])


def _to_out(s: AsicSolicitud) -> AsicSolicitudOut:
    d = AsicSolicitudOut.model_validate(s)
    if s.proyecto:
        d.planta_nombre = s.proyecto.nombre_comercial
    return d


@router.get("", response_model=list[AsicSolicitudOut])
def list_solicitudes(
    codigo_sic_contrato: str | None = Query(None),
    contrato_interno: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto))
    if codigo_sic_contrato:
        q = q.filter(AsicSolicitud.codigo_sic_contrato == codigo_sic_contrato)
    if contrato_interno:
        q = q.filter(AsicSolicitud.contrato_interno == contrato_interno)
    if proyecto_id:
        q = q.filter(AsicSolicitud.proyecto_id == proyecto_id)
    rows = q.order_by(AsicSolicitud.fecha_solicitud.desc().nullslast(), AsicSolicitud.id.desc()).all()
    return [_to_out(s) for s in rows]


@router.patch("/{id}", response_model=AsicSolicitudOut)
def patch_solicitud(
    id: int,
    data: dict,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    if not s:
        from fastapi import HTTPException
        raise HTTPException(404, "No encontrado")
    for k, v in data.items():
        if hasattr(s, k):
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _to_out(db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first())


@router.post("", response_model=AsicSolicitudOut, status_code=201)
def create_solicitud(
    data: AsicSolicitudCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = AsicSolicitud(**data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == s.id).first())


@router.post("/cambios", response_model=AsicCambioOut, status_code=201)
def create_cambio(
    data: AsicCambioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    obj = AsicCambioContrato(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/gescon/diccionario", response_model=list[GesconDiccionarioOut])
def list_diccionario(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(GesconDiccionario).order_by(GesconDiccionario.codigo_contrato).all()


@router.post("/gescon/diccionario", response_model=GesconDiccionarioOut, status_code=201)
def upsert_diccionario(
    data: GesconDiccionarioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    existing = db.query(GesconDiccionario).filter_by(codigo_contrato=data.codigo_contrato).first()
    if existing:
        existing.nombre = data.nombre
        db.commit()
        db.refresh(existing)
        return existing
    obj = GesconDiccionario(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
