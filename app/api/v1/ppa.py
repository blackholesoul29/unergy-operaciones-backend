import logging
import unicodedata
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import PPAContrato, PPATarifa, PPACompromisoEnergia, Proyecto, AsicSolicitud
from app.models.cumplimiento import CumplimientoMensual

logger = logging.getLogger(__name__)
from app.models.clientes import Cliente
from app.models.contratos import ppa_contrato_proyectos_table, IppMensual, PPAResponsable
from app.services.documentos import set_enlace_documento
from pydantic import BaseModel
from app.schemas.ppa import (
    PPAContratoCreate, PPAContratoUpdate, PPAContratoOut,
    PPATarifaIn, PPATarifaOut,
    PPACompromisoIn, PPACompromisoOut,
    PPAResponsableIn, PPAResponsableUpdate, PPAResponsableOut, PPAResponsableAsignar,
)

router = APIRouter(prefix="/ppa", tags=["PPA"])


def _load_options():
    return [
        selectinload(PPAContrato.proyectos),
        selectinload(PPAContrato.responsable),
        selectinload(PPAContrato.comprador),
        selectinload(PPAContrato.vendedor),
        selectinload(PPAContrato.tarifas),
        selectinload(PPAContrato.compromisos_energia),
        # El @property `carpeta_link` recorre esta relacion en cada fila
        # serializada -- sin esto, un listado dispara un SELECT por fila.
        selectinload(PPAContrato.documentos_comerciales),
    ]


def _sync_partes_from_clientes(contrato: PPAContrato, db: Session):
    """Si hay comprador_id/vendedor_id, sincroniza nombre y NIT desde el cliente."""
    if contrato.comprador_id:
        c = db.query(Cliente).filter(Cliente.id == contrato.comprador_id).first()
        if c:
            contrato.comprador_nombre = c.razon_social_nombre
            contrato.comprador_nit = c.nit_cedula
    if contrato.vendedor_id:
        v = db.query(Cliente).filter(Cliente.id == contrato.vendedor_id).first()
        if v:
            contrato.vendedor_nombre = v.razon_social_nombre
            contrato.vendedor_nit = v.nit_cedula


def _get_contrato_or_404(id: int, db: Session) -> PPAContrato:
    c = (
        db.query(PPAContrato)
        .options(*_load_options())
        .filter(PPAContrato.id == id, PPAContrato.deleted_at.is_(None))
        .first()
    )
    if not c:
        raise HTTPException(404, "Contrato PPA no encontrado")
    return c


def _set_proyectos(contrato: PPAContrato, proyecto_ids: list[int], db: Session):
    proyectos = db.query(Proyecto).filter(Proyecto.id.in_(proyecto_ids)).all() if proyecto_ids else []
    contrato.proyectos = proyectos


def _validar_fecha_fin_vs_asic(contrato: PPAContrato, db: Session) -> None:
    """El fecha_fin del contrato PPA macro es manual, pero no puede quedar por
    delante de una fecha_fin ya registrada en sus plantas GESCON (asic_solicitudes) —
    ver `_validar_fecha_fin_vs_ppa` en asic.py para la regla inversa."""
    if contrato.fecha_fin is None:
        return
    filtros = [AsicSolicitud.contrato_ppa_id == contrato.id]
    if contrato.numero_codigo_contrato:
        filtros.append(AsicSolicitud.contrato_interno == contrato.numero_codigo_contrato)
    peor = (
        db.query(AsicSolicitud)
        .filter(AsicSolicitud.fecha_fin > contrato.fecha_fin)
        .filter(or_(*filtros))
        .order_by(AsicSolicitud.fecha_fin.desc())
        .first()
    )
    if peor:
        raise HTTPException(
            422,
            f"No se puede fijar la fecha de fin en {contrato.fecha_fin.isoformat()}: "
            f"el registro GESCON \"{peor.codigo_sic_contrato or peor.id}\" ya tiene "
            f"fecha_fin {peor.fecha_fin.isoformat()}, posterior. Corrige ese registro "
            f"primero o usa una fecha de fin mayor.",
        )


@router.get("", response_model=list[PPAContratoOut])
def list_contratos(
    proyecto_id: int | None = Query(None),
    q: str | None = Query(None),
    tipo_contrato: str | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(PPAContrato).filter(PPAContrato.deleted_at.is_(None)).options(*_load_options())
    if tipo_contrato is not None:
        query = query.filter(PPAContrato.tipo_contrato == tipo_contrato)
    if proyecto_id is not None:
        query = query.join(
            ppa_contrato_proyectos_table,
            PPAContrato.id == ppa_contrato_proyectos_table.c.contrato_id
        ).filter(ppa_contrato_proyectos_table.c.proyecto_id == proyecto_id)
    if q:
        like = f"%{q}%"
        query = query.join(
            ppa_contrato_proyectos_table,
            PPAContrato.id == ppa_contrato_proyectos_table.c.contrato_id,
            isouter=True,
        ).join(
            Proyecto,
            ppa_contrato_proyectos_table.c.proyecto_id == Proyecto.id,
            isouter=True,
        ).filter(
            Proyecto.nombre_comercial.ilike(like)
            | PPAContrato.nombre_interno.ilike(like)
            | PPAContrato.numero_codigo_contrato.ilike(like)
            | PPAContrato.comprador_nombre.ilike(like)
        ).distinct()
    return (
        query
        .order_by(PPAContrato.fecha_inicio.desc().nullslast(), PPAContrato.id.desc())
        .limit(limit)
        .all()
    )


@router.post("", response_model=PPAContratoOut, status_code=201)
def create_contrato(
    data: PPAContratoCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    payload = data.model_dump(exclude={"proyecto_ids"})
    carpeta_link = payload.pop("carpeta_link", None)
    contrato = PPAContrato(**payload)
    db.add(contrato)
    db.flush()
    _validar_fecha_fin_vs_asic(contrato, db)
    _set_proyectos(contrato, data.proyecto_ids, db)
    _sync_partes_from_clientes(contrato, db)
    if carpeta_link:
        set_enlace_documento(db, ppa_contrato_id=contrato.id, url=carpeta_link,
                              nombre="Enlace Drive del contrato")
    db.commit()
    return _get_contrato_or_404(contrato.id, db)


@router.get("/partes")
def get_partes(db: Session = Depends(get_db), _=Depends(get_current_user)):
    compradores = (
        db.query(PPAContrato.comprador_nombre, PPAContrato.comprador_nit)
        .filter(PPAContrato.comprador_nombre.isnot(None))
        .distinct()
        .all()
    )
    vendedores = (
        db.query(PPAContrato.vendedor_nombre, PPAContrato.vendedor_nit)
        .filter(PPAContrato.vendedor_nombre.isnot(None))
        .distinct()
        .all()
    )
    return {
        "compradores": [{"nombre": r.comprador_nombre, "nit": r.comprador_nit} for r in compradores],
        "vendedores": [{"nombre": r.vendedor_nombre, "nit": r.vendedor_nit} for r in vendedores],
    }


# ── Empresas responsables de PPA (catálogo) ──────────────────────────────────
# OJO: estas rutas van ANTES de `@router.get("/{id}")`, si no FastAPI intenta
# resolver "responsables" como el id del contrato y responde 422.

def _responsable_or_404(rid: int, db: Session) -> PPAResponsable:
    r = db.query(PPAResponsable).filter(PPAResponsable.id == rid).first()
    if not r:
        raise HTTPException(404, "Responsable no encontrado")
    return r


def _validar_nombre_libre(nombre: str, db: Session, excepto_id: int | None = None) -> str:
    nombre = (nombre or "").strip()
    if not nombre:
        raise HTTPException(422, "El nombre del responsable no puede estar vacío")
    q = db.query(PPAResponsable).filter(func.lower(PPAResponsable.nombre) == nombre.lower())
    if excepto_id is not None:
        q = q.filter(PPAResponsable.id != excepto_id)
    if q.first():
        raise HTTPException(409, f'Ya existe un responsable llamado "{nombre}"')
    return nombre


@router.get("/responsables", response_model=list[PPAResponsableOut])
def list_responsables(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Catálogo de empresas responsables, con cuántos contratos vivos tiene cada una."""
    conteos = dict(
        db.query(PPAContrato.responsable_id, func.count(PPAContrato.id))
        .filter(PPAContrato.deleted_at.is_(None), PPAContrato.responsable_id.isnot(None))
        .group_by(PPAContrato.responsable_id)
        .all()
    )
    rows = db.query(PPAResponsable).order_by(PPAResponsable.nombre).all()
    return [
        PPAResponsableOut(
            id=r.id, nombre=r.nombre,
            incluir_en_cumplimiento=r.incluir_en_cumplimiento,
            n_contratos=conteos.get(r.id, 0),
        )
        for r in rows
    ]


@router.post("/responsables", response_model=PPAResponsableOut, status_code=201)
def create_responsable(data: PPAResponsableIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    nombre = _validar_nombre_libre(data.nombre, db)
    r = PPAResponsable(nombre=nombre, incluir_en_cumplimiento=data.incluir_en_cumplimiento)
    db.add(r)
    db.commit()
    return PPAResponsableOut(id=r.id, nombre=r.nombre,
                             incluir_en_cumplimiento=r.incluir_en_cumplimiento, n_contratos=0)


@router.patch("/responsables/{rid}", response_model=PPAResponsableOut)
def update_responsable(rid: int, data: PPAResponsableUpdate,
                       db: Session = Depends(get_db), _=Depends(get_current_user)):
    r = _responsable_or_404(rid, db)
    if data.nombre is not None:
        r.nombre = _validar_nombre_libre(data.nombre, db, excepto_id=rid)
    if data.incluir_en_cumplimiento is not None:
        r.incluir_en_cumplimiento = data.incluir_en_cumplimiento
    db.commit()
    n = (db.query(func.count(PPAContrato.id))
         .filter(PPAContrato.deleted_at.is_(None), PPAContrato.responsable_id == rid).scalar()) or 0
    return PPAResponsableOut(id=r.id, nombre=r.nombre,
                             incluir_en_cumplimiento=r.incluir_en_cumplimiento, n_contratos=n)


@router.delete("/responsables/{rid}", status_code=204)
def delete_responsable(rid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Borra un responsable. Se bloquea si aún tiene contratos: reasignarlos primero
    deja explícito qué pasa con ellos (el ON DELETE SET NULL los volvería visibles
    en la matriz sin que nadie se entere)."""
    r = _responsable_or_404(rid, db)
    n = (db.query(func.count(PPAContrato.id))
         .filter(PPAContrato.deleted_at.is_(None), PPAContrato.responsable_id == rid).scalar()) or 0
    if n:
        raise HTTPException(409, f'No se puede eliminar "{r.nombre}": tiene {n} contrato(s). '
                                 "Reasígnalos a otro responsable primero.")
    db.delete(r)
    db.commit()


@router.post("/responsables/asignar")
def asignar_responsable(data: PPAResponsableAsignar,
                        db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Asigna (o desasigna, con responsable_id=null) el responsable de varios contratos."""
    if data.responsable_id is not None:
        _responsable_or_404(data.responsable_id, db)
    if not data.contrato_ids:
        return {"actualizados": 0}
    n = (
        db.query(PPAContrato)
        .filter(PPAContrato.id.in_(data.contrato_ids), PPAContrato.deleted_at.is_(None))
        .update({PPAContrato.responsable_id: data.responsable_id}, synchronize_session=False)
    )
    db.commit()
    return {"actualizados": n}


# Contratos de los que Unergy NO es responsable (confirmado por Juan, 2026-08-08).
# Solo se usa para la clasificación inicial; después se administra desde la UI.
RESPONSABLE_EXTERNO_CONTRATOS = [
    "BIA Delta 1", "BIA Naos 1", "BIA Naos 2", "BIA Naos 3", "BIA Polaris 1",
    "Sol&Cielo7", "Sol&Cielo9",
]


def _norm_nombre(s: str | None) -> str:
    """Clave de comparación tolerante: sin tildes, sin espacios ni símbolos.
    'Sol&Cielo 7' == 'sol y cielo7'? No —solo ignora lo no alfanumérico— pero sí
    'Sol&Cielo7' == 'SOL&CIELO 7'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s.lower() if ch.isalnum())


def sembrar_responsables_ppa(db: Session, clasificar: bool = True) -> dict:
    """Crea el catálogo base de responsables y, si nadie ha clasificado todavía,
    asigna Unergy a todos los contratos salvo los de RESPONSABLE_EXTERNO_CONTRATOS.

    Idempotente y ONE-SHOT para la clasificación: en cuanto un contrato tiene
    responsable, no vuelve a tocar asignaciones (un redeploy no debe revertir lo
    que se cambió a mano en la UI).
    """
    catalogo: dict[str, PPAResponsable] = {}
    for nombre, incluir in (("Unergy", True), ("Externo", False)):
        obj = db.query(PPAResponsable).filter(PPAResponsable.nombre == nombre).first()
        if obj is None:
            obj = PPAResponsable(nombre=nombre, incluir_en_cumplimiento=incluir)
            db.add(obj)
            db.flush()
        catalogo[nombre] = obj

    rep = {"unergy": 0, "externo": 0, "sin_match": [], "clasifico": False}
    ya_clasificado = (
        db.query(PPAContrato.id).filter(PPAContrato.responsable_id.isnot(None)).first() is not None
    )
    if not clasificar or ya_clasificado:
        db.commit()
        return rep

    externos = {_norm_nombre(n): n for n in RESPONSABLE_EXTERNO_CONTRATOS}
    vistos: set[str] = set()
    for c in db.query(PPAContrato).filter(PPAContrato.deleted_at.is_(None)).all():
        clave = next(
            (k for k in (_norm_nombre(c.nombre_interno), _norm_nombre(c.numero_codigo_contrato))
             if k and k in externos),
            None,
        )
        if clave:
            c.responsable_id = catalogo["Externo"].id
            vistos.add(clave)
            rep["externo"] += 1
        else:
            c.responsable_id = catalogo["Unergy"].id
            rep["unergy"] += 1
    db.commit()
    rep["clasifico"] = True
    rep["sin_match"] = [n for k, n in externos.items() if k not in vistos]
    return rep


def _compute_visibility(contrato: PPAContrato, db: Session) -> dict:
    """Compute estado_cumplimiento, dias_restantes, cobertura_actual_pct for a PPA contract."""
    today = date.today()
    result: dict = {}

    # dias_restantes
    if contrato.fecha_fin:
        result["dias_restantes"] = (contrato.fecha_fin - today).days
    else:
        result["dias_restantes"] = None

    # cobertura_actual_pct: current month gen / commitment as %
    compromiso = (
        db.query(PPACompromisoEnergia)
        .filter(
            PPACompromisoEnergia.contrato_id == contrato.id,
            PPACompromisoEnergia.año == today.year,
            PPACompromisoEnergia.mes == today.month,
        )
        .first()
    )
    min_mwh = float(compromiso.energia_minima) if compromiso and compromiso.energia_minima is not None else None

    # Try to get actual generation from cumplimiento_mensual
    cumpl = (
        db.query(CumplimientoMensual)
        .filter(
            CumplimientoMensual.contrato_ppa_id == contrato.id,
            CumplimientoMensual.anio == today.year,
            CumplimientoMensual.mes == today.month,
        )
        .first()
    )
    gen_mwh = float(cumpl.gen_total_mwh) if cumpl and cumpl.gen_total_mwh is not None else None

    if min_mwh and min_mwh > 0 and gen_mwh is not None:
        result["cobertura_actual_pct"] = round(gen_mwh / min_mwh * 100, 1)
    else:
        result["cobertura_actual_pct"] = None

    # estado_cumplimiento
    if result["cobertura_actual_pct"] is not None:
        if result["cobertura_actual_pct"] >= 100:
            result["estado_cumplimiento"] = "on_track"
        elif result["cobertura_actual_pct"] >= 80:
            result["estado_cumplimiento"] = "at_risk"
        else:
            result["estado_cumplimiento"] = "deficit"
    elif contrato.fecha_fin and contrato.fecha_fin < today:
        result["estado_cumplimiento"] = "deficit"
    else:
        result["estado_cumplimiento"] = None

    return result


@router.get("/resumen-global")
def get_resumen_global(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Portfolio-level PPA summary with aggregated visibility metrics."""
    today = date.today()
    contratos = (
        db.query(PPAContrato)
        .filter(PPAContrato.deleted_at.is_(None))
        .options(*_load_options())
        .all()
    )

    total_contratos = len(contratos)
    vigentes = [c for c in contratos if c.fecha_fin and c.fecha_fin >= today]
    vencidos = [c for c in contratos if c.fecha_fin and c.fecha_fin < today]
    sin_fecha = [c for c in contratos if not c.fecha_fin]

    # Compute visibility per contract
    on_track = 0
    at_risk = 0
    deficit = 0
    sin_datos = 0
    contratos_resumen = []
    for c in contratos:
        vis = _compute_visibility(c, db)
        estado = vis.get("estado_cumplimiento")
        if estado == "on_track":
            on_track += 1
        elif estado == "at_risk":
            at_risk += 1
        elif estado == "deficit":
            deficit += 1
        else:
            sin_datos += 1

        contratos_resumen.append({
            "id": c.id,
            "nombre_interno": c.nombre_interno,
            "numero_codigo_contrato": c.numero_codigo_contrato,
            "comprador_nombre": c.comprador_nombre,
            "tipo_contrato": c.tipo_contrato,
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else None,
            "estado_cumplimiento": vis.get("estado_cumplimiento"),
            "dias_restantes": vis.get("dias_restantes"),
            "cobertura_actual_pct": vis.get("cobertura_actual_pct"),
        })

    return {
        "total_contratos": total_contratos,
        "vigentes": len(vigentes),
        "vencidos": len(vencidos),
        "sin_fecha_fin": len(sin_fecha),
        "cumplimiento": {
            "on_track": on_track,
            "at_risk": at_risk,
            "deficit": deficit,
            "sin_datos": sin_datos,
        },
        "contratos": contratos_resumen,
    }


@router.get("/{id}", response_model=PPAContratoOut)
def get_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = _get_contrato_or_404(id, db)
    out = PPAContratoOut.model_validate(c, from_attributes=True)
    vis = _compute_visibility(c, db)
    out.estado_cumplimiento = vis.get("estado_cumplimiento")
    out.dias_restantes = vis.get("dias_restantes")
    out.cobertura_actual_pct = vis.get("cobertura_actual_pct")
    return out


@router.patch("/{id}")
def update_contrato(
    id: int,
    data: PPAContratoUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_contrato_or_404(id, db)
    update_data = data.model_dump(exclude_unset=True, exclude={"proyecto_ids"})
    carpeta_link_set = "carpeta_link" in update_data
    carpeta_link = update_data.pop("carpeta_link", None)
    for k, v in update_data.items():
        setattr(contrato, k, v)
    if carpeta_link_set:
        set_enlace_documento(db, ppa_contrato_id=contrato.id, url=carpeta_link,
                              nombre="Enlace Drive del contrato")
    if data.proyecto_ids is not None:
        _set_proyectos(contrato, data.proyecto_ids, db)
    _sync_partes_from_clientes(contrato, db)
    _validar_fecha_fin_vs_asic(contrato, db)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Error al guardar contrato PPA %s", id)
        raise HTTPException(500, detail=f"Error al guardar: {e}")
    try:
        updated = _get_contrato_or_404(id, db)
        return PPAContratoOut.model_validate(updated, from_attributes=True).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error al serializar contrato PPA %s después de update", id)
        raise HTTPException(500, detail=f"Error al serializar respuesta: {e}")


@router.delete("/{id}", status_code=204)
def delete_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    contrato = _get_contrato_or_404(id, db)
    razones = []

    n_liquidaciones = (
        db.query(CumplimientoMensual)
        .filter(CumplimientoMensual.contrato_ppa_id == contrato.id)
        .count()
    )
    if n_liquidaciones:
        razones.append(f"Tiene {n_liquidaciones} liquidación(es) de cumplimiento asociadas")

    n_asic = (
        db.query(AsicSolicitud)
        .filter(AsicSolicitud.contrato_ppa_id == contrato.id)
        .count()
    )
    if n_asic:
        razones.append(f"Tiene {n_asic} registro(s) GESCON/ASIC vinculados")

    if razones:
        raise HTTPException(409, f"No se puede eliminar: {'; '.join(razones)}.")

    # Python datetime (no func.now()): asignar un ClauseElement SQL a la columna hace
    # que el hook de auditoría (_diff_attrs: `old != new`) reviente con
    # "Boolean value of this clause is not defined" → 500 en cualquier borrado de PPA.
    contrato.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.put("/{id}/tarifas", response_model=list[PPATarifaOut])
def replace_tarifas(
    id: int,
    rows: list[PPATarifaIn],
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_contrato_or_404(id, db)
    db.query(PPATarifa).filter(PPATarifa.contrato_id == id).delete()
    db.add_all([PPATarifa(contrato_id=id, **r.model_dump()) for r in rows])
    db.commit()
    return db.query(PPATarifa).filter(PPATarifa.contrato_id == id).order_by(PPATarifa.año, PPATarifa.mes).all()


@router.put("/{id}/compromisos", response_model=list[PPACompromisoOut])
def replace_compromisos(
    id: int,
    rows: list[PPACompromisoIn],
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_contrato_or_404(id, db)
    db.query(PPACompromisoEnergia).filter(PPACompromisoEnergia.contrato_id == id).delete()
    db.add_all([PPACompromisoEnergia(contrato_id=id, **r.model_dump()) for r in rows])
    db.commit()
    return (
        db.query(PPACompromisoEnergia)
        .filter(PPACompromisoEnergia.contrato_id == id)
        .order_by(PPACompromisoEnergia.año, PPACompromisoEnergia.mes)
        .all()
    )


# ── IPP mensual global (numerador de la indexación de energía) ────────────────
class IppMensualIn(BaseModel):
    año: int
    mes: int
    valor: float


@router.get("/ipp/mensual")
def list_ipp_mensual(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = db.query(IppMensual).order_by(IppMensual.año, IppMensual.mes).all()
    return [{"año": r.año, "mes": r.mes, "valor": float(r.valor)} for r in rows]


@router.put("/ipp/mensual")
def upsert_ipp_mensual(rows: list[IppMensualIn], db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Upsert de valores IPP por (año, mes). No borra los demás períodos."""
    for r in rows:
        obj = db.query(IppMensual).filter(IppMensual.año == r.año, IppMensual.mes == r.mes).first()
        if obj is None:
            db.add(IppMensual(año=r.año, mes=r.mes, valor=r.valor))
        else:
            obj.valor = r.valor
    db.commit()
    out = db.query(IppMensual).order_by(IppMensual.año, IppMensual.mes).all()
    return [{"año": o.año, "mes": o.mes, "valor": float(o.valor)} for o in out]
