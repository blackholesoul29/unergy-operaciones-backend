from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import AsicSolicitud, PPAContrato
from app.models.asic import (
    AsicCambioContrato, GesconDiccionario,
    TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum,
)
from app.models.cumplimiento import CumplimientoMensual
from app.schemas.asic import AsicSolicitudOut, AsicSolicitudCreate, AsicSolicitudUpdate, AsicCambioCreate, AsicCambioOut, GesconDiccionarioCreate, GesconDiccionarioOut

router = APIRouter(prefix="/asic", tags=["ASIC"])


def _auto_terminate(db: Session, solicitud: AsicSolicitud) -> int:
    """
    Al publicar una terminación, su `fecha_fin` se estampa como `fecha_fin` del/los
    registro(s) vigente(s) del MISMO código SIC (nivel planta). Los registros NO se
    marcan 'terminado': siguen 'publicado' para que Cumplimiento los prorratee HASTA la
    fecha y los excluya DESPUÉS — el histórico previo a la terminación queda intacto.

    El contrato PPA comercial NO se da por terminado por una sola planta: su `fecha_fin`
    (fin contractual, fuente de verdad del contrato firmado) sólo se mueve cuando TODAS
    las plantas del contrato interno están terminadas — es decir, cuando ya no queda
    ningún registro/modificación 'publicado' con `fecha_fin` vacía. Así un PPA
    multi-planta (p. ej. Terpel 1, 12 plantas hasta 2039) conserva su fin aunque una de
    sus plantas/SIC se termine antes. (Un SIC ⇒ una planta; un contrato ⇒ varios SIC.)
    """
    if (
        solicitud.tipo_solicitud != TipoSolicitudAsicEnum.terminacion
        or solicitud.estado_solicitud != EstadoSolicitudAsicEnum.publicado
        or not solicitud.codigo_sic_contrato
        or solicitud.fecha_fin is None
    ):
        return 0

    fecha_term = solicitud.fecha_fin

    # 1) Nivel planta: estampar fecha_fin en los registros del mismo SIC.
    targets = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.id != solicitud.id,
            AsicSolicitud.codigo_sic_contrato == solicitud.codigo_sic_contrato,
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud.in_([
                TipoSolicitudAsicEnum.registro,
                TipoSolicitudAsicEnum.modificacion,
            ]),
        )
        .all()
    )

    contratos_internos: set[str] = set()
    for t in targets:
        if t.fecha_fin is None or t.fecha_fin > fecha_term:
            t.fecha_fin = fecha_term
        if t.contrato_interno:
            contratos_internos.add(t.contrato_interno)
    db.flush()  # que el paso 2 vea las fechas recién estampadas

    # 2) Nivel contrato: terminar el PPA SÓLO si ya no queda ninguna planta abierta.
    for contrato_interno in contratos_internos:
        registros = (
            db.query(AsicSolicitud)
            .filter(
                AsicSolicitud.contrato_interno == contrato_interno,
                AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
                AsicSolicitud.tipo_solicitud.in_([
                    TipoSolicitudAsicEnum.registro,
                    TipoSolicitudAsicEnum.modificacion,
                ]),
            )
            .all()
        )
        if not registros or any(r.fecha_fin is None for r in registros):
            # queda al menos una planta abierta → el contrato sigue vigente
            continue

        fin_contrato = max(r.fecha_fin for r in registros)
        ppas = (
            db.query(PPAContrato)
            .filter(
                PPAContrato.numero_codigo_contrato == contrato_interno,
                PPAContrato.deleted_at.is_(None),
            )
            .all()
        )
        for ppa in ppas:
            if ppa.fecha_fin != fin_contrato:
                ppa.fecha_fin = fin_contrato

    return len(targets)


def _to_out(s: AsicSolicitud) -> AsicSolicitudOut:
    d = AsicSolicitudOut.model_validate(s)
    if s.proyecto:
        d.planta_nombre = s.proyecto.nombre_comercial
    return d


def _planta_por_sic(db: Session, sics: set[str]) -> dict[str, str]:
    """
    Mapa código SIC -> nombre(s) de planta, derivado de los registros vigentes
    (registro/modificacion) que SÍ tienen proyecto. Sirve para mostrar la planta
    en filas que no llevan proyecto_id (p. ej. terminaciones), sin almacenar el FK
    —lo que reintroduciría el bug de Cumplimiento—. Display-only.
    """
    if not sics:
        return {}
    rows = (
        db.query(AsicSolicitud)
        .options(joinedload(AsicSolicitud.proyecto))
        .filter(
            AsicSolicitud.codigo_sic_contrato.in_(sics),
            AsicSolicitud.proyecto_id.isnot(None),
            AsicSolicitud.tipo_solicitud.in_([
                TipoSolicitudAsicEnum.registro,
                TipoSolicitudAsicEnum.modificacion,
            ]),
        )
        .all()
    )
    nombres: dict[str, list[str]] = {}
    for r in rows:
        if not r.proyecto or not r.proyecto.nombre_comercial:
            continue
        nm = r.proyecto.nombre_comercial
        bucket = nombres.setdefault(r.codigo_sic_contrato, [])
        if nm not in bucket:
            bucket.append(nm)
    return {sic: " · ".join(ns) for sic, ns in nombres.items()}


def _enriquecer_planta(db: Session, outs: list[AsicSolicitudOut]) -> list[AsicSolicitudOut]:
    """Rellena planta_nombre en filas sin proyecto resuelto, vía su código SIC."""
    pendientes = {o.codigo_sic_contrato for o in outs if not o.planta_nombre and o.codigo_sic_contrato}
    if not pendientes:
        return outs
    mapa = _planta_por_sic(db, pendientes)
    for o in outs:
        if not o.planta_nombre and o.codigo_sic_contrato:
            o.planta_nombre = mapa.get(o.codigo_sic_contrato)
    return outs


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
    return _enriquecer_planta(db, [_to_out(s) for s in rows])


@router.patch("/{id}", response_model=AsicSolicitudOut)
def patch_solicitud(
    id: int,
    data: AsicSolicitudUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    if not s:
        raise HTTPException(404, "No encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    return _enriquecer_planta(db, [_to_out(s)])[0]


@router.post("", response_model=AsicSolicitudOut, status_code=201)
def create_solicitud(
    data: AsicSolicitudCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = AsicSolicitud(**data.model_dump())
    db.add(s)
    db.flush()
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == s.id).first()
    return _enriquecer_planta(db, [_to_out(s)])[0]


@router.delete("/{id}", status_code=204)
def delete_solicitud(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(AsicSolicitud).filter(AsicSolicitud.id == id).first()
    if not s:
        raise HTTPException(404, "Registro GESCON no encontrado")

    razones = []

    n_cambios = (
        db.query(AsicCambioContrato)
        .filter(AsicCambioContrato.solicitud_id == id)
        .count()
    )
    if n_cambios:
        razones.append(f"Tiene {n_cambios} cambio(s) de contrato asociados")

    if s.contrato_ppa_id:
        n_cumpl = (
            db.query(CumplimientoMensual)
            .filter(CumplimientoMensual.contrato_ppa_id == s.contrato_ppa_id)
            .count()
        )
        if n_cumpl:
            ppa = db.query(PPAContrato).filter(PPAContrato.id == s.contrato_ppa_id).first()
            nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}" if ppa else f"ID {s.contrato_ppa_id}"
            razones.append(f"Vinculado al contrato PPA \"{nombre_ppa}\" que tiene {n_cumpl} registro(s) de cumplimiento")
    elif s.contrato_interno:
        ppa = (
            db.query(PPAContrato)
            .filter(
                PPAContrato.numero_codigo_contrato == s.contrato_interno,
                PPAContrato.deleted_at.is_(None),
            )
            .first()
        )
        if ppa:
            n_cumpl = (
                db.query(CumplimientoMensual)
                .filter(CumplimientoMensual.contrato_ppa_id == ppa.id)
                .count()
            )
            if n_cumpl:
                nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
                razones.append(f"Vinculado al contrato PPA \"{nombre_ppa}\" que tiene {n_cumpl} registro(s) de cumplimiento")

    if razones:
        raise HTTPException(409, f"No se puede eliminar: {'; '.join(razones)}.")

    db.delete(s)
    db.commit()


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
