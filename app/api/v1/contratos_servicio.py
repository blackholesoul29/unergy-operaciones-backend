from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.contratos import ContratoServicio, PagoServicio
from app.models.clientes import Cliente
from app.models.fronteras import Frontera
from app.schemas.contratos_servicio import (
    ContratoServicioCreate, ContratoServicioUpdate, ContratoServicioOut,
    PagoServicioCreate, PagoServicioUpdate, PagoServicioOut,
    ImportarIndexacionEntry, FilaFactura,
)
from app.utils.proyecto_matching import find_proyecto_by_name

router = APIRouter(prefix="/contratos-servicio", tags=["ContratoServicio"])


def _load_options():
    return [
        selectinload(ContratoServicio.contratante),
        selectinload(ContratoServicio.prestador),
        selectinload(ContratoServicio.fronteras),
    ]


def _get_or_404(id: int, db: Session) -> ContratoServicio:
    c = db.query(ContratoServicio).options(*_load_options()).filter(ContratoServicio.id == id).first()
    if not c:
        raise HTTPException(404, "Contrato no encontrado")
    return c


def _sync_fronteras(contrato: ContratoServicio, frontera_ids: list[int], db: Session):
    """Deja el contrato vinculado exactamente a `frontera_ids`.

    Asignar la relación deja que SQLAlchemy calcule el diff (borra los vínculos
    que sobran, inserta los nuevos). Los ids repetidos en el payload colapsan al
    resolverlos contra la BD, así no se viola uq_contrato_frontera.
    """
    fronteras = []
    if frontera_ids:
        fronteras = (
            db.query(Frontera)
            .filter(Frontera.id.in_(set(frontera_ids)), Frontera.deleted_at.is_(None))
            .all()
        )
        faltantes = set(frontera_ids) - {f.id for f in fronteras}
        if faltantes:
            raise HTTPException(400, f"Fronteras no encontradas: {sorted(faltantes)}")
    contrato.fronteras = fronteras


def _sync_partes(contrato: ContratoServicio, db: Session):
    if contrato.contratante_id:
        cl = db.query(Cliente).filter(Cliente.id == contrato.contratante_id).first()
        if cl:
            contrato.contratante_nombre = cl.razon_social_nombre
            contrato.contratante_nit = cl.nit_cedula
    if contrato.prestador_id:
        pr = db.query(Cliente).filter(Cliente.id == contrato.prestador_id).first()
        if pr:
            contrato.prestador_nombre = pr.razon_social_nombre
            contrato.prestador_nit = pr.nit_cedula


@router.get("", response_model=list[ContratoServicioOut])
def list_contratos(
    tipo: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    codigo_tsf: str | None = Query(None),
    limit: int = Query(500, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    import re
    from sqlalchemy import or_, text as sa_text
    q = db.query(ContratoServicio).options(*_load_options())
    if tipo:
        q = q.filter(ContratoServicio.servicio_aplica == tipo)

    if proyecto_id:
        conds = [ContratoServicio.proyecto_id == proyecto_id]

        # Coincidencia por código Sun Factory si el proyecto tiene codigo_tsf
        if codigo_tsf:
            conds.append(ContratoServicio.codigo_sun_factory == codigo_tsf)

        # Fallback: busca en nombre_proyecto_ref usando el número de 4 dígitos
        # del nombre del proyecto (ej. "MGS 0010 - Villanueva" → "0010")
        try:
            row = db.execute(
                sa_text("SELECT nombre_comercial FROM proyectos WHERE id = :id"),
                {"id": proyecto_id},
            ).first()
            if row and row[0]:
                nums = re.findall(r'\d{4}', row[0])
                for num in nums:
                    conds.append(
                        ContratoServicio.nombre_proyecto_ref.ilike(f'%{num}%')
                    )
        except Exception:
            pass

        q = q.filter(or_(*conds))
    elif codigo_tsf:
        q = q.filter(ContratoServicio.codigo_sun_factory == codigo_tsf)

    return q.order_by(
        ContratoServicio.fecha_inicio.desc().nullslast(),
        ContratoServicio.id.desc(),
    ).limit(limit).all()


@router.post("", response_model=ContratoServicioOut, status_code=201)
def create_contrato(
    data: ContratoServicioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    payload = data.model_dump()
    frontera_ids = payload.pop("frontera_ids", []) or []
    contrato = ContratoServicio(**payload)
    db.add(contrato)
    db.flush()
    _sync_partes(contrato, db)
    _sync_fronteras(contrato, frontera_ids, db)
    db.commit()
    return _get_or_404(contrato.id, db)


@router.post("/importar-indexacion")
def importar_indexacion(
    tipo: str = Query(..., description="'anual' o 'mensual'"),
    payload: list[ImportarIndexacionEntry] = Body(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Carga masiva de filas de indexación O&M para múltiples proyectos.

    Body: [{proyecto: str, filas: [{anio, ipc_aplicado, valor}]}]
    tipo: 'anual' | 'mensual'
    Retorna: {actualizados: [str], no_encontrados: [str]}
    """
    if tipo not in ("anual", "mensual"):
        raise HTTPException(400, "tipo debe ser 'anual' o 'mensual'")

    campo = "indexacion_anual" if tipo == "anual" else "indexacion_mensual"
    actualizados: list[str] = []
    no_encontrados: list[str] = []

    for entrada in payload:
        nombre = entrada.proyecto.strip()
        proy = find_proyecto_by_name(db, nombre)
        if not proy:
            no_encontrados.append(nombre)
            continue

        contrato = (
            db.query(ContratoServicio)
            .filter(
                ContratoServicio.proyecto_id == proy.id,
                ContratoServicio.servicio_aplica == "mantenimiento",
            )
            .first()
        )
        if not contrato:
            no_encontrados.append(nombre)
            continue

        filas_serializadas = [f.model_dump() for f in entrada.filas]
        setattr(contrato, campo, filas_serializadas)
        flag_modified(contrato, campo)
        actualizados.append(proy.nombre_comercial or nombre)

    db.commit()
    return {"actualizados": actualizados, "no_encontrados": no_encontrados}


@router.get("/{id}", response_model=ContratoServicioOut)
def get_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_or_404(id, db)


@router.patch("/{id}", response_model=ContratoServicioOut)
def update_contrato(
    id: int,
    data: ContratoServicioUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_or_404(id, db)
    payload = data.model_dump(exclude_unset=True)
    # None/ausente = no tocar las fronteras actuales; [] = desvincular todas
    frontera_ids = payload.pop("frontera_ids", None)
    for k, v in payload.items():
        setattr(contrato, k, v)
    _sync_partes(contrato, db)
    if frontera_ids is not None:
        _sync_fronteras(contrato, frontera_ids, db)
    db.commit()
    return _get_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_contrato(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    contrato = _get_or_404(id, db)
    db.delete(contrato)
    db.commit()


# ── Facturas Solenium / Inversionistas ────────────────────────────────────────

@router.patch("/{id}/facturas-solenium", response_model=ContratoServicioOut)
def update_facturas_solenium(
    id: int,
    facturas: list[FilaFactura] = Body(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_or_404(id, db)
    contrato.facturas_solenium = [f.model_dump() for f in facturas]
    flag_modified(contrato, "facturas_solenium")
    db.commit()
    return _get_or_404(id, db)


@router.patch("/{id}/facturas-inversionistas", response_model=ContratoServicioOut)
def update_facturas_inversionistas(
    id: int,
    facturas: list[FilaFactura] = Body(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    contrato = _get_or_404(id, db)
    contrato.facturas_inversionistas = [f.model_dump() for f in facturas]
    flag_modified(contrato, "facturas_inversionistas")
    db.commit()
    return _get_or_404(id, db)


# ── Pagos de servicio ──────────────────────────────────────────────────────────

@router.get("/{id}/pagos", response_model=list[PagoServicioOut])
def list_pagos(
    id: int,
    año: int | None = Query(None),
    mes: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    q = db.query(PagoServicio).filter(PagoServicio.contrato_id == id)
    if año is not None:
        q = q.filter(PagoServicio.año == año)
    if mes is not None:
        q = q.filter(PagoServicio.mes == mes)
    return q.order_by(PagoServicio.año.desc(), PagoServicio.mes.desc()).all()


@router.post("/{id}/pagos", response_model=PagoServicioOut, status_code=201)
def create_pago(
    id: int,
    data: PagoServicioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    pago = PagoServicio(contrato_id=id, **data.model_dump())
    db.add(pago)
    db.commit()
    db.refresh(pago)
    return pago


@router.patch("/{id}/pagos/{pago_id}", response_model=PagoServicioOut)
def update_pago(
    id: int,
    pago_id: int,
    data: PagoServicioUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    pago = db.query(PagoServicio).filter(PagoServicio.id == pago_id, PagoServicio.contrato_id == id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(pago, k, v)
    db.commit()
    db.refresh(pago)
    return pago


@router.delete("/{id}/pagos/{pago_id}", status_code=204)
def delete_pago(
    id: int,
    pago_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    pago = db.query(PagoServicio).filter(PagoServicio.id == pago_id, PagoServicio.contrato_id == id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    db.delete(pago)
    db.commit()
