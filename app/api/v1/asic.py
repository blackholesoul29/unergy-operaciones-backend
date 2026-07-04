from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, and_, func
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
from app.utils.gescon_vigencia import resolver_vigencias

router = APIRouter(prefix="/asic", tags=["ASIC"])


def _auto_terminate(db: Session, solicitud: AsicSolicitud) -> int:
    """
    Al publicar una terminación, su `fecha_fin` se estampa como `fecha_fin` del/los
    registro(s) vigente(s) del MISMO código SIC (nivel planta). Los registros NO se
    marcan 'terminado': siguen 'publicado' para que Cumplimiento los prorratee HASTA la
    fecha y los excluya DESPUÉS — el histórico previo a la terminación queda intacto.

    El `fecha_fin` del contrato PPA comercial es un campo manual (fuente de verdad del
    contrato firmado): esta función NO lo toca. Inferirlo automáticamente a partir de
    fechas sueltas en registros/modificaciones de ASIC resultó frágil — cualquier
    `fecha_fin` cargada en una planta por un motivo ajeno a una terminación real (p.ej.
    vigencia de registro GESCON) contaminaba el cierre del contrato completo. Si el
    contrato macro debe cerrarse, se edita directamente en la pestaña PPA. Ver
    `_validar_fecha_fin_vs_ppa` para la regla inversa: ninguna planta puede tener una
    fecha_fin posterior a la del contrato macro.
    """
    if (
        solicitud.tipo_solicitud != TipoSolicitudAsicEnum.terminacion
        or solicitud.estado_solicitud != EstadoSolicitudAsicEnum.publicado
        or not solicitud.codigo_sic_contrato
        or solicitud.fecha_fin is None
    ):
        return 0

    fecha_term = solicitud.fecha_fin

    # Nivel planta: estampar fecha_fin en los registros del mismo SIC.
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

    for t in targets:
        if t.fecha_fin is None or t.fecha_fin > fecha_term:
            t.fecha_fin = fecha_term

    return len(targets)


def _validar_fecha_fin_vs_ppa(db: Session, solicitud: AsicSolicitud) -> None:
    """Ninguna fecha_fin de un registro GESCON puede ser posterior a la fecha_fin
    (manual) de su contrato PPA macro. Evita que una planta quede "vigente" mas alla
    de lo que el contrato comercial permite."""
    if solicitud.fecha_fin is None:
        return
    ppa = _resolver_ppa_para(solicitud, db)
    if ppa is None or ppa.fecha_fin is None:
        return
    if solicitud.fecha_fin > ppa.fecha_fin:
        nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
        raise HTTPException(
            422,
            f"La fecha de fin ({solicitud.fecha_fin.isoformat()}) no puede ser "
            f"posterior a la del contrato PPA \"{nombre_ppa}\" "
            f"({ppa.fecha_fin.isoformat()}). Corrige la fecha o actualiza primero "
            f"el contrato macro.",
        )


def _to_out(s: AsicSolicitud) -> AsicSolicitudOut:
    d = AsicSolicitudOut.model_validate(s)
    if s.proyecto:
        d.planta_nombre = s.proyecto.nombre_comercial
    return d


def _aplicar_vigencia(db: Session, outs: list[AsicSolicitudOut]) -> list[AsicSolicitudOut]:
    """Rellena fecha_fin_efectiva / es_version_vigente en cada salida.

    La resolución corre SIEMPRE sobre el universo completo de solicitudes
    publicadas (no sobre el subconjunto filtrado del request): el relevo que
    recorta a una fila puede venir de otra planta u otro contrato que el filtro
    excluyó. Filas no publicadas o desistimientos no participan del walk:
    conservan su fecha_fin cruda y es_version_vigente=False.
    """
    universo = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud != TipoSolicitudAsicEnum.desistimiento,
        )
        .order_by(
            AsicSolicitud.fecha_inicio.asc().nullsfirst(),
            AsicSolicitud.fecha_solicitud.asc().nullsfirst(),
            AsicSolicitud.created_at.asc(),
        )
        .all()
    )
    vigencias = resolver_vigencias(universo)
    for o in outs:
        v = vigencias.get(o.id)
        if v is not None:
            o.fecha_fin_efectiva = v.fecha_fin_efectiva
            o.es_version_vigente = v.vigente
        else:
            o.fecha_fin_efectiva = o.fecha_fin
            o.es_version_vigente = False
    return outs


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
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s) for s in rows]))


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
    _validar_fecha_fin_vs_ppa(db, s)
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s)]))[0]


@router.post("", response_model=AsicSolicitudOut, status_code=201)
def create_solicitud(
    data: AsicSolicitudCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = AsicSolicitud(**data.model_dump())
    db.add(s)
    db.flush()
    _validar_fecha_fin_vs_ppa(db, s)
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == s.id).first()
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s)]))[0]


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


def _resolver_ppa_para(s: AsicSolicitud, db: Session) -> PPAContrato | None:
    """Contrato PPA canónico de un registro GESCON: por FK contrato_ppa_id, o si no,
    casando el código `contrato_interno` con `numero_codigo_contrato` (no borrado)."""
    if s.contrato_ppa_id:
        return (
            db.query(PPAContrato)
            .filter(PPAContrato.id == s.contrato_ppa_id, PPAContrato.deleted_at.is_(None))
            .first()
        )
    if s.contrato_interno and s.contrato_interno.strip():
        return (
            db.query(PPAContrato)
            .filter(
                PPAContrato.numero_codigo_contrato == s.contrato_interno,
                PPAContrato.deleted_at.is_(None),
            )
            .first()
        )
    return None


@router.post("/backfill-nombre-interno")
def backfill_nombre_interno(
    dry_run: bool = Query(True, description="true (default): solo reporta, no modifica."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Completa `nombre_interno` en registros GESCON que lo tienen vacío, copiándolo del
    contrato PPA al que pertenecen (nombre real, "alusivo al contrato específico"). De paso
    vincula `contrato_ppa_id` si faltaba. No inventa nombres: los que no tienen PPA con
    nombre se reportan sin tocar. Idempotente. `dry_run=false` aplica en una transacción."""
    faltantes = (
        db.query(AsicSolicitud)
        .filter(
            or_(AsicSolicitud.nombre_interno.is_(None), func.trim(AsicSolicitud.nombre_interno) == ""),
            or_(
                AsicSolicitud.contrato_ppa_id.isnot(None),
                and_(AsicSolicitud.contrato_interno.isnot(None), func.trim(AsicSolicitud.contrato_interno) != ""),
            ),
        )
        .all()
    )

    resueltos, no_resueltos = [], []
    for s in faltantes:
        ppa = _resolver_ppa_para(s, db)
        nombre = (ppa.nombre_interno or "").strip() if ppa else ""
        if ppa and nombre:
            resueltos.append({
                "id": s.id,
                "contrato_interno": s.contrato_interno,
                "nombre_propuesto": nombre,
                "vincula_ppa_id": (ppa.id if not s.contrato_ppa_id else None),
            })
        else:
            no_resueltos.append({
                "id": s.id,
                "contrato_interno": s.contrato_interno,
                "motivo": "sin PPA que casar" if not ppa else "el PPA no tiene nombre_interno",
            })

    reporte = {
        "dry_run": dry_run,
        "total_sin_nombre": len(faltantes),
        "a_actualizar": len(resueltos),
        "sin_resolver": len(no_resueltos),
        "resueltos": resueltos,
        "no_resueltos": no_resueltos,
    }
    if dry_run:
        return reporte

    try:
        for r in resueltos:
            s = db.query(AsicSolicitud).filter(AsicSolicitud.id == r["id"]).first()
            if not s:
                continue
            s.nombre_interno = r["nombre_propuesto"]
            if r["vincula_ppa_id"] and not s.contrato_ppa_id:
                s.contrato_ppa_id = r["vincula_ppa_id"]
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"El backfill falló y se revirtió: {type(e).__name__}: {e}")

    reporte["ejecutado"] = True
    return reporte


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
