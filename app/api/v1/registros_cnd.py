"""API de la seccion "Registros CND/ASIC".

Seguimiento del proceso de conexion (CREG 174 -> 9.4) anclado a un Proyecto existente.
Acceso: admin + operaciones.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto
from app.models.registros_cnd import (
    RegistroConexion, RegistroParametros93, RegistroEquipoFrontera, RegistroDocumento,
)
from app.schemas.registros_cnd import (
    RegistroConexionCreate, RegistroConexionUpdate, TransicionIn,
    Parametros93In, EquipoCreate, EquipoUpdate, EquipoOut,
    DocumentoCreate, DocumentoUpdate, DocumentoOut, ProyectoDisponibleOut,
)
from app.services.registros_cnd import service, state_machine as sm
from app.services.registros_cnd.dominio import (
    ETAPAS_ACTUALES, ETAPAS_FUTURAS, ETIQUETAS_ETAPA, HITOS,
    TipoDocumento, TipoEquipoFrontera, TipoVisitaProtecciones, Responsable,
)
from app.services.registros_cnd.validaciones_93 import Entradas93, validar_93
from app.services.registros_cnd.correos import generar_correo, TIPOS_CORREO

router = APIRouter(prefix="/registros-cnd", tags=["Registros CND/ASIC"])


def _check_operaciones(current: Usuario) -> None:
    if current.rol.value not in ("admin", "operaciones"):
        raise HTTPException(status_code=403, detail="Requiere rol operaciones o admin")


def _get_registro(db: Session, registro_id: int) -> RegistroConexion:
    reg = db.get(RegistroConexion, registro_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return reg


# ---------------------------------------------------------------------------
# Catalogos (para que el frontend renderice etapas/transiciones/hitos)
# ---------------------------------------------------------------------------
@router.get("/catalogos")
def catalogos(current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    return {
        "etapas": [{"value": e, "label": ETIQUETAS_ETAPA[e]} for e in ETAPAS_ACTUALES],
        "etapas_futuras": [{"value": e, "label": ETIQUETAS_ETAPA[e]} for e in ETAPAS_FUTURAS],
        "hitos": [
            {"codigo": h["key"], "etapa": h["etapa"], "peso_default": h["peso_default"], "descripcion": h["descripcion"]}
            for h in HITOS
        ],
        "transiciones": {e: sm.get_etapa_def(e)["transiciones"] for e in [*ETAPAS_ACTUALES, *ETAPAS_FUTURAS]},
        "iniciales": {e: sm.get_etapa_def(e)["inicial"] for e in [*ETAPAS_ACTUALES, *ETAPAS_FUTURAS]},
        "tipos_documento": [v for k, v in vars(TipoDocumento).items() if not k.startswith("_")],
        "tipos_equipo": [v for k, v in vars(TipoEquipoFrontera).items() if not k.startswith("_")],
        "tipos_visita": [TipoVisitaProtecciones.VIRTUAL, TipoVisitaProtecciones.PRESENCIAL],
        "responsables": [v for k, v in vars(Responsable).items() if not k.startswith("_")],
        "tipos_correo": list(TIPOS_CORREO),
    }


# ---------------------------------------------------------------------------
# Proyectos disponibles (sin registro aun) — para el dialogo "Registrar"
# ---------------------------------------------------------------------------
@router.get("/proyectos-disponibles", response_model=list[ProyectoDisponibleOut])
def proyectos_disponibles(
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    con_registro = {r.proyecto_id for r in db.query(RegistroConexion.proyecto_id).all()}
    query = db.query(Proyecto)
    if hasattr(Proyecto, "deleted_at"):
        query = query.filter(Proyecto.deleted_at.is_(None))
    if q:
        query = query.filter(Proyecto.nombre_comercial.ilike(f"%{q}%"))
    proyectos = query.order_by(Proyecto.nombre_comercial.asc()).limit(300).all()
    return [p for p in proyectos if p.id not in con_registro]


# ---------------------------------------------------------------------------
# CRUD de registros
# ---------------------------------------------------------------------------
@router.get("")
def listar(db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    registros = db.query(RegistroConexion).all()
    return [service.resumen_ligero(db, r) for r in registros]


@router.post("", status_code=201)
def crear(
    data: RegistroConexionCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    try:
        reg = service.crear_registro(db, **data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return service.construir_resumen(db, reg)


@router.get("/{registro_id}")
def obtener(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    return service.construir_resumen(db, reg)


@router.patch("/{registro_id}")
def actualizar(
    registro_id: int,
    data: RegistroConexionUpdate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(reg, k, v)
    db.commit()
    db.refresh(reg)
    return service.construir_resumen(db, reg)


@router.post("/{registro_id}/transicion")
def transicion(
    registro_id: int,
    data: TransicionIn,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    try:
        service.registrar_transicion(db, reg, data.etapa, data.a_estado, nota=data.nota, actor=data.actor)
    except sm.TransicionInvalidaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.refresh(reg)
    return service.construir_resumen(db, reg)


# ---------------------------------------------------------------------------
# Parametros 9.3 + validacion
# ---------------------------------------------------------------------------
@router.get("/{registro_id}/parametros-93")
def obtener_parametros_93(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    return reg.parametros_93


@router.put("/{registro_id}/parametros-93")
def upsert_parametros_93(
    registro_id: int,
    data: Parametros93In,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    params = reg.parametros_93
    if params is None:
        params = RegistroParametros93(registro_id=reg.id)
        db.add(params)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(params, k, v)
    db.commit()
    db.refresh(params)
    return params


@router.get("/{registro_id}/validacion-93")
def validacion_93(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    p = reg.parametros_93
    if p is None:
        return {"valido": True, "resultados": [], "sin_parametros": True}
    entradas = Entradas93(
        icc_subtrans_pico_kap=p.icc_subtrans_pico_kap,
        icc_subtrans_3f_ka=p.icc_subtrans_3f_ka,
        icc_subtrans_2f_ka=p.icc_subtrans_2f_ka,
        icc_subtrans_1f_ka=p.icc_subtrans_1f_ka,
        icc_estado_estable_ka=p.icc_estado_estable_ka,
        voltaje_max_kv=p.voltaje_max_kv,
        voltaje_nominal_kv=p.voltaje_nominal_kv,
        voltaje_min_kv=p.voltaje_min_kv,
        in_eq_ka=p.in_eq_ka,
    )
    return validar_93(entradas)


# ---------------------------------------------------------------------------
# Equipos de frontera
# ---------------------------------------------------------------------------
@router.get("/{registro_id}/equipos", response_model=list[EquipoOut])
def listar_equipos(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    return reg.equipos


@router.post("/{registro_id}/equipos", response_model=EquipoOut, status_code=201)
def crear_equipo(
    registro_id: int, data: EquipoCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    eq = RegistroEquipoFrontera(registro_id=reg.id, **data.model_dump())
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return eq


@router.patch("/{registro_id}/equipos/{equipo_id}", response_model=EquipoOut)
def actualizar_equipo(
    registro_id: int, equipo_id: int, data: EquipoUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    eq = db.get(RegistroEquipoFrontera, equipo_id)
    if eq is None or eq.registro_id != registro_id:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(eq, k, v)
    db.commit()
    db.refresh(eq)
    return eq


@router.delete("/{registro_id}/equipos/{equipo_id}", status_code=204)
def eliminar_equipo(
    registro_id: int, equipo_id: int,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    eq = db.get(RegistroEquipoFrontera, equipo_id)
    if eq is None or eq.registro_id != registro_id:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    db.delete(eq)
    db.commit()


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
@router.get("/{registro_id}/documentos", response_model=list[DocumentoOut])
def listar_documentos(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    return reg.documentos


@router.post("/{registro_id}/documentos", response_model=DocumentoOut, status_code=201)
def crear_documento(
    registro_id: int, data: DocumentoCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    doc = RegistroDocumento(registro_id=reg.id, **data.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{registro_id}/documentos/{documento_id}", response_model=DocumentoOut)
def actualizar_documento(
    registro_id: int, documento_id: int, data: DocumentoUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    doc = db.get(RegistroDocumento, documento_id)
    if doc is None or doc.registro_id != registro_id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{registro_id}/documentos/{documento_id}", status_code=204)
def eliminar_documento(
    registro_id: int, documento_id: int,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    doc = db.get(RegistroDocumento, documento_id)
    if doc is None or doc.registro_id != registro_id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
@router.post("/{registro_id}/alertas/recomputar")
def recomputar_alertas(registro_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    creadas = service.recomputar_alertas(db, reg)
    db.refresh(reg)
    return {
        "creadas": len(creadas),
        "alertas": [
            {"tipo": a.tipo, "mensaje": a.mensaje, "estado": a.estado, "fecha_disparo": a.fecha_disparo}
            for a in reg.alertas
        ],
    }


# ---------------------------------------------------------------------------
# Correos tipo (borradores)
# ---------------------------------------------------------------------------
@router.post("/{registro_id}/correos/{tipo}")
def generar_correo_tipo(
    registro_id: int, tipo: str,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_operaciones(current)
    reg = _get_registro(db, registro_id)
    try:
        return generar_correo(reg, tipo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
