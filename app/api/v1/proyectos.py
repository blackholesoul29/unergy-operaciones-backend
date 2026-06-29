from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Proyecto
from app.models.proyectos import (
    ProyectoInversionista, ProyectoInfoTecnica,
    ProyectoGrupoPanel, ProyectoInversor, ProyectoContacto,
)
from app.schemas.proyectos import (
    ProyectoCreate, ProyectoUpdate, ProyectoOut,
    ProyectoInversionistaCreate, ProyectoInversionistaUpdate, ProyectoInversionistaOut,
    ProyectoInfoTecnicaCreate, ProyectoInfoTecnicaOut,
    ProyectoGrupoPanelCreate, ProyectoGrupoPanelUpdate, ProyectoGrupoPanelOut,
    ProyectoInversorCreate, ProyectoInversorUpdate, ProyectoInversorOut,
    ProyectoContactoCreate, ProyectoContactoUpdate, ProyectoContactoOut,
)
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/proyectos", tags=["Proyectos"])


def _get_proyecto_or_404(id: int, db: Session) -> Proyecto:
    p = (
        db.query(Proyecto)
        .options(
            selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente),
            selectinload(Proyecto.info_tecnica),
            selectinload(Proyecto.grupos_panel),
            selectinload(Proyecto.inversores),
            selectinload(Proyecto.contactos),
            selectinload(Proyecto.servicio_representacion),
        )
        .filter(Proyecto.id == id)
        .first()
    )
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


# ── Proyectos ─────────────────────────────────────────────────────────────────

SERVICIO_FILTER_MAP = {
    "operacion": Proyecto.srv_operacion,
    "representacion": Proyecto.srv_representacion,
    "cgm": Proyecto.srv_cgm,
    "ppa": Proyecto.srv_ppa,
    "promotor": Proyecto.srv_promotor,
    "rec": Proyecto.srv_rec,
}


@router.get("", response_model=PaginatedResponse[ProyectoOut])
def list_proyectos(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
    q: str | None = None,
    estado: str | None = None,
    tipo_proyecto: str | None = None,
    portafolio_id: int | None = None,
    servicio: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(Proyecto).filter(Proyecto.deleted_at.is_(None)).options(
        selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente),
        selectinload(Proyecto.info_tecnica),
        selectinload(Proyecto.grupos_panel),
        selectinload(Proyecto.inversores),
        selectinload(Proyecto.contactos),
        selectinload(Proyecto.servicio_representacion),
    )
    if q:
        query = query.filter(Proyecto.nombre_comercial.ilike(f"%{q}%"))
    if estado:
        query = query.filter(Proyecto.estado == estado)
    if tipo_proyecto:
        query = query.filter(Proyecto.tipo_proyecto == tipo_proyecto)
    if portafolio_id:
        query = query.filter(Proyecto.portafolio_id == portafolio_id)
    if servicio and servicio in SERVICIO_FILTER_MAP:
        query = query.filter(SERVICIO_FILTER_MAP[servicio] == True)
    total = query.count()
    items = query.order_by(Proyecto.nombre_comercial).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.post("", response_model=ProyectoOut, status_code=201)
def create_proyecto(data: ProyectoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    proyecto = Proyecto(**data.model_dump())
    db.add(proyecto)
    db.commit()
    db.refresh(proyecto)
    return _get_proyecto_or_404(proyecto.id, db)


@router.get("/{id}", response_model=ProyectoOut)
def get_proyecto(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_proyecto_or_404(id, db)


# Columnas con restricción UNIQUE en el modelo Proyecto. Si se intenta asignar a un
# proyecto un valor ya usado por otro, Postgres lanza IntegrityError; sin manejo, eso
# sube como 500 sin detalle y el frontend solo muestra "Error" (ver bug API ID Unergy).
_UNIQUE_COLS = {
    "sub_project": "API ID Unergy",
    "topic_slug": "topic slug",
}


@router.patch("/{id}", response_model=ProyectoOut)
def update_proyecto(id: int, data: ProyectoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")

    payload = data.model_dump(exclude_unset=True)

    # Chequeo proactivo de campos únicos: da un mensaje accionable que nombra el
    # proyecto en conflicto, en vez de un IntegrityError opaco.
    for col, etiqueta in _UNIQUE_COLS.items():
        nuevo = payload.get(col)
        if nuevo in (None, ""):
            continue
        conflicto = (
            db.query(Proyecto)
            .filter(getattr(Proyecto, col) == nuevo, Proyecto.id != id)
            .first()
        )
        if conflicto:
            raise HTTPException(
                409,
                f"El {etiqueta} '{nuevo}' ya está asignado al proyecto "
                f"'{conflicto.nombre_comercial}' (ID {conflicto.id}). "
                f"Cada {etiqueta} debe ser único.",
            )

    for k, v in payload.items():
        setattr(p, k, v)
    try:
        db.commit()
    except IntegrityError:
        # Backstop ante carreras o cualquier otra restricción única no cubierta arriba.
        db.rollback()
        raise HTTPException(
            409,
            "No se pudo guardar: algún valor único (p. ej. API ID Unergy o topic slug) "
            "ya está en uso por otro proyecto.",
        )
    return _get_proyecto_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_proyecto(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")

    # Verificar si hay registros de negocio que impiden la eliminación
    business_records = (
        p.fallas or p.mantenimientos or p.liquidaciones or p.contratos_arriendo
        or p.asic_solicitudes or p.rec_procesos or p.promotor_seguimientos
        or p.contratos_servicio or p.ppa_contratos or p.kpis
        or p.servicio_operacion or p.servicio_representacion or p.servicio_cgm
        or p.fronteras or p.subproyectos
    )
    if business_records:
        raise HTTPException(
            409,
            "No se puede eliminar el proyecto porque tiene registros operativos asociados "
            "(fallas, mantenimientos, liquidaciones, contratos, etc.). "
            "Elimine primero esos registros."
        )

    # Eliminar sub-recursos directos del proyecto
    db.query(ProyectoInversionista).filter_by(proyecto_id=id).delete()
    db.query(ProyectoGrupoPanel).filter_by(proyecto_id=id).delete()
    db.query(ProyectoInversor).filter_by(proyecto_id=id).delete()
    db.query(ProyectoContacto).filter_by(proyecto_id=id).delete()
    db.query(ProyectoInfoTecnica).filter_by(proyecto_id=id).delete()

    db.delete(p)
    db.commit()


@router.patch("/{id}/servicios", response_model=ProyectoOut)
def toggle_servicios(id: int, data: dict, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    allowed = {"srv_operacion", "srv_representacion", "srv_cgm", "srv_ppa", "srv_promotor", "srv_rec"}
    for k, v in data.items():
        if k in allowed:
            setattr(p, k, v)
    db.commit()
    return _get_proyecto_or_404(id, db)


# ── Info Técnica ──────────────────────────────────────────────────────────────

@router.get("/{id}/info-tecnica", response_model=ProyectoInfoTecnicaOut)
def get_info_tecnica(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    it = db.query(ProyectoInfoTecnica).filter_by(proyecto_id=id).first()
    if not it:
        raise HTTPException(404, "Info técnica no encontrada")
    return it


@router.put("/{id}/info-tecnica", response_model=ProyectoInfoTecnicaOut)
def upsert_info_tecnica(id: int, data: ProyectoInfoTecnicaCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    it = db.query(ProyectoInfoTecnica).filter_by(proyecto_id=id).first()
    if it:
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(it, k, v)
    else:
        it = ProyectoInfoTecnica(proyecto_id=id, **data.model_dump())
        db.add(it)
    db.commit()
    db.refresh(it)
    return it


# ── Grupos Panel ──────────────────────────────────────────────────────────────

@router.get("/{id}/grupos-panel", response_model=list[ProyectoGrupoPanelOut])
def list_grupos_panel(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    return db.query(ProyectoGrupoPanel).filter_by(proyecto_id=id).all()


@router.post("/{id}/grupos-panel", response_model=ProyectoGrupoPanelOut, status_code=201)
def add_grupo_panel(id: int, data: ProyectoGrupoPanelCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    gp = ProyectoGrupoPanel(proyecto_id=id, **data.model_dump())
    db.add(gp)
    db.commit()
    db.refresh(gp)
    return gp


@router.patch("/{id}/grupos-panel/{gp_id}", response_model=ProyectoGrupoPanelOut)
def update_grupo_panel(id: int, gp_id: int, data: ProyectoGrupoPanelUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    gp = db.query(ProyectoGrupoPanel).filter_by(id=gp_id, proyecto_id=id).first()
    if not gp:
        raise HTTPException(404, "Grupo de paneles no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(gp, k, v)
    db.commit()
    db.refresh(gp)
    return gp


@router.delete("/{id}/grupos-panel/{gp_id}", status_code=204)
def delete_grupo_panel(id: int, gp_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    gp = db.query(ProyectoGrupoPanel).filter_by(id=gp_id, proyecto_id=id).first()
    if not gp:
        raise HTTPException(404, "Grupo de paneles no encontrado")
    db.delete(gp)
    db.commit()


# ── Inversores ────────────────────────────────────────────────────────────────

@router.get("/{id}/inversores", response_model=list[ProyectoInversorOut])
def list_inversores(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    return db.query(ProyectoInversor).filter_by(proyecto_id=id).all()


@router.post("/{id}/inversores", response_model=ProyectoInversorOut, status_code=201)
def add_inversor(id: int, data: ProyectoInversorCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    inv = ProyectoInversor(proyecto_id=id, **data.model_dump())
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.patch("/{id}/inversores/{inv_id}", response_model=ProyectoInversorOut)
def update_inversor(id: int, inv_id: int, data: ProyectoInversorUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    inv = db.query(ProyectoInversor).filter_by(id=inv_id, proyecto_id=id).first()
    if not inv:
        raise HTTPException(404, "Inversor no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(inv, k, v)
    db.commit()
    db.refresh(inv)
    return inv


@router.delete("/{id}/inversores/{inv_id}", status_code=204)
def delete_inversor(id: int, inv_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    inv = db.query(ProyectoInversor).filter_by(id=inv_id, proyecto_id=id).first()
    if not inv:
        raise HTTPException(404, "Inversor no encontrado")
    db.delete(inv)
    db.commit()


# ── Contactos ─────────────────────────────────────────────────────────────────

@router.get("/{id}/contactos", response_model=list[ProyectoContactoOut])
def list_contactos(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    return db.query(ProyectoContacto).filter_by(proyecto_id=id).all()


@router.post("/{id}/contactos", response_model=ProyectoContactoOut, status_code=201)
def add_contacto(id: int, data: ProyectoContactoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    c = ProyectoContacto(proyecto_id=id, **data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.patch("/{id}/contactos/{c_id}", response_model=ProyectoContactoOut)
def update_contacto(id: int, c_id: int, data: ProyectoContactoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(ProyectoContacto).filter_by(id=c_id, proyecto_id=id).first()
    if not c:
        raise HTTPException(404, "Contacto no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{id}/contactos/{c_id}", status_code=204)
def delete_contacto(id: int, c_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(ProyectoContacto).filter_by(id=c_id, proyecto_id=id).first()
    if not c:
        raise HTTPException(404, "Contacto no encontrado")
    db.delete(c)
    db.commit()


# ── Inversionistas ────────────────────────────────────────────────────────────

@router.get("/{id}/inversionistas", response_model=list[ProyectoInversionistaOut])
def list_inversionistas(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    return (
        db.query(ProyectoInversionista)
        .options(selectinload(ProyectoInversionista.cliente))
        .filter(ProyectoInversionista.proyecto_id == id)
        .all()
    )


@router.post("/{id}/inversionistas", response_model=ProyectoInversionistaOut, status_code=201)
def add_inversionista(id: int, data: ProyectoInversionistaCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_proyecto_or_404(id, db)
    duplicate = db.query(ProyectoInversionista).filter_by(
        proyecto_id=id, cliente_id=data.cliente_id
    ).first()
    if duplicate:
        raise HTTPException(409, "Este cliente ya es inversionista de este proyecto")
    inv = ProyectoInversionista(proyecto_id=id, **data.model_dump())
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return db.query(ProyectoInversionista).options(
        selectinload(ProyectoInversionista.cliente)
    ).filter(ProyectoInversionista.id == inv.id).first()


@router.patch("/{id}/inversionistas/{inv_id}", response_model=ProyectoInversionistaOut)
def update_inversionista(id: int, inv_id: int, data: ProyectoInversionistaUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    inv = db.query(ProyectoInversionista).filter_by(id=inv_id, proyecto_id=id).first()
    if not inv:
        raise HTTPException(404, "Inversionista no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(inv, k, v)
    db.commit()
    return db.query(ProyectoInversionista).options(
        selectinload(ProyectoInversionista.cliente)
    ).filter(ProyectoInversionista.id == inv_id).first()


@router.delete("/{id}/inversionistas/{inv_id}", status_code=204)
def remove_inversionista(id: int, inv_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    inv = db.query(ProyectoInversionista).filter_by(id=inv_id, proyecto_id=id).first()
    if not inv:
        raise HTTPException(404, "Inversionista no encontrado")
    db.delete(inv)
    db.commit()
