from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.contratos import ContratoServicio, PagoServicio, ContratoFactura
from app.models.clientes import Cliente
from app.models.fronteras import Frontera
from app.schemas.contratos_servicio import (
    ContratoServicioCreate, ContratoServicioUpdate, ContratoServicioOut,
    PagoServicioCreate, PagoServicioUpdate, PagoServicioOut,
    ImportarIndexacionEntry,
    ContratoFacturaCreate, ContratoFacturaUpdate, ContratoFacturaOut,
)
from app.utils.proyecto_matching import find_proyecto_by_name
from app.utils.nombre_matching import mejor_candidato, core_tokens
from app.services.documentos import set_enlace_documento

router = APIRouter(prefix="/contratos-servicio", tags=["ContratoServicio"])


def _load_options():
    return [
        selectinload(ContratoServicio.contratante),
        selectinload(ContratoServicio.prestador),
        # Sin esto el listado dispara un SELECT por fila para pintar el nombre
        # del proyecto (112 contratos de representación = 112 queries).
        selectinload(ContratoServicio.proyecto),
        selectinload(ContratoServicio.fronteras),
        selectinload(ContratoServicio.inversionista),
        # Igual: el @property `enlace_drive` recorre esta relacion en cada
        # fila serializada -- sin esto, un listado de ~112 contratos de
        # representacion dispara un SELECT por fila.
        selectinload(ContratoServicio.documentos_comerciales),
    ]


def _get_or_404(id: int, db: Session) -> ContratoServicio:
    c = db.query(ContratoServicio).options(*_load_options()).filter(ContratoServicio.id == id).first()
    if not c:
        raise HTTPException(404, "Contrato no encontrado")
    return c


def _sync_fronteras(contrato: ContratoServicio, frontera_ids: list[int], db: Session):
    """Deja el contrato vinculado exactamente a `frontera_ids`.

    Asignar la relación deja que SQLAlchemy calcule el diff (borra los
    vínculos que sobran, inserta los nuevos). Los ids repetidos en el
    payload colapsan al resolverlos contra la BD, así no se viola
    uq_contrato_frontera."""
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
        # Si el contrato ya tiene proyecto, las fronteras deben ser de ese
        # mismo proyecto -- evita vincular por error un punto de medida de
        # otra planta (el contrato es legal, la frontera es fisica; no
        # tiene sentido que no coincidan de proyecto).
        if contrato.proyecto_id is not None:
            de_otro_proyecto = [f.id for f in fronteras if f.proyecto_id != contrato.proyecto_id]
            if de_otro_proyecto:
                raise HTTPException(
                    400,
                    f"Estas fronteras no pertenecen al proyecto del contrato: {sorted(de_otro_proyecto)}",
                )
    contrato.fronteras = fronteras


def _resolver_cliente_id(db: Session, nombre: str | None, nit: str | None) -> int | None:
    """Resuelve un cliente_id a partir del nombre/NIT de texto libre del
    wizard -- el campo nunca obliga a elegir del autocomplete, así que
    contratante_id/prestador_id casi nunca se poblaban (auditoría de
    Clientes 2026-08-27: 0/162 contratos_servicio en producción). Sin esto,
    "condiciones económicas" del panel 360 y otras vistas de /clientes
    quedaban silenciosamente vacías.

    NIT primero (exacto, normalizado); si no, nombre parecido -- pero exige
    ADEMÁS solapamiento real de tokens (no solo similitud de texto): el
    backfill manual del mismo día encontró casos reales como "BALI ENERGY
    S.A.S." emparejando por error con "INENERGY S.A.S." (0 tokens en común,
    solo parecido de caracteres)."""
    if nit:
        key = "".join(ch for ch in nit if ch.isalnum())
        if key:
            con_nit = (
                db.query(Cliente)
                .filter(Cliente.deleted_at.is_(None), Cliente.nit_cedula.isnot(None))
                .all()
            )
            iguales = [c for c in con_nit if "".join(ch for ch in c.nit_cedula if ch.isalnum()) == key]
            if len(iguales) == 1:
                return iguales[0].id
    if nombre:
        clientes = db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all()
        candidatos = [(c, [c.razon_social_nombre]) for c in clientes]
        item, _score = mejor_candidato(nombre, candidatos)
        if item and (core_tokens(nombre) & core_tokens(item.razon_social_nombre)):
            return item.id
    return None


def _sync_partes(contrato: ContratoServicio, db: Session):
    if not contrato.contratante_id:
        contrato.contratante_id = _resolver_cliente_id(db, contrato.contratante_nombre, contrato.contratante_nit)
    if not contrato.prestador_id:
        contrato.prestador_id = _resolver_cliente_id(db, contrato.prestador_nombre, contrato.prestador_nit)

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
    enlace_drive = payload.pop("enlace_drive", None)
    contrato = ContratoServicio(**payload)
    db.add(contrato)
    db.flush()
    _sync_partes(contrato, db)
    _sync_fronteras(contrato, frontera_ids, db)
    if enlace_drive:
        set_enlace_documento(db, contrato_servicio_id=contrato.id, url=enlace_drive,
                              nombre="Enlace Drive del contrato")
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


# ── Duplicados de representacion ──────────────────────────────────────────────
# Van ANTES de /{id}: si no, FastAPI intenta leer "duplicados" como el id.

@router.get("/duplicados-representacion")
def duplicados_representacion(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Informe de contratos de representacion que son el mismo registro repetido.

    Solo lee. Separa los grupos que se pueden fusionar sin perder nada de los que
    se contradicen y necesitan que alguien decida.
    """
    from app.services.representacion_dedup import revisar

    contratos = db.query(ContratoServicio).filter(
        ContratoServicio.servicio_aplica == "representacion"
    ).all()
    return revisar(contratos)


@router.post("/fusionar-representacion")
def fusionar_representacion(
    ids: list[int] | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Fusiona los duplicados de representacion.

    Por cada grupo: completa el registro que se conserva con los datos que solo
    tenian los otros y borra los otros. Nunca sobreescribe un valor existente, y
    salta cualquier grupo donde dos registros se contradigan.

    `ids` limita la operacion a los grupos que contengan alguno de esos ids; sin
    el, fusiona todos los grupos limpios.
    """
    from app.services.representacion_dedup import agrupar, analizar

    contratos = db.query(ContratoServicio).filter(
        ContratoServicio.servicio_aplica == "representacion"
    ).all()
    por_id = {c.id: c for c in contratos}

    fusionados, eliminados, saltados = [], 0, []
    for grupo in agrupar(contratos):
        r = analizar(grupo)
        if not r["fusionable"]:
            saltados.append({"ids": [g.id for g in grupo],
                             "conflictos": r["conflictos"]})
            continue
        if ids and not any(g.id in ids for g in grupo):
            continue

        conservado = por_id[r["conservar"]]
        for campo, valor in r["valores"].items():
            if campo == "enlace_drive":
                # No es una columna real (property de solo lectura, ver
                # services/documentos.py) -- no admite setattr.
                set_enlace_documento(db, contrato_servicio_id=conservado.id, url=valor,
                                      nombre="Enlace Drive del contrato")
                continue
            setattr(conservado, campo, valor)
            if campo in ("indexacion_cgm", "indexacion_representacion"):
                flag_modified(conservado, campo)
        for cid in r["eliminar"]:
            db.delete(por_id[cid])
            eliminados += 1
        fusionados.append({"conservado": conservado.id, "eliminados": r["eliminar"],
                           "campos_completados": sorted(r["valores"])})

    db.commit()
    return {"grupos_fusionados": len(fusionados), "contratos_eliminados": eliminados,
            "detalle": fusionados, "saltados_por_conflicto": saltados}


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
    enlace_drive_set = "enlace_drive" in payload
    enlace_drive = payload.pop("enlace_drive", None)
    for k, v in payload.items():
        setattr(contrato, k, v)
    if enlace_drive_set:
        set_enlace_documento(db, contrato_servicio_id=contrato.id, url=enlace_drive,
                              nombre="Enlace Drive del contrato")
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
# Reemplaza los JSONB facturas_solenium/facturas_inversionistas (auditoria de
# "JSON suelto" 2026-08-30) -- mismo patron CRUD que /pagos.

@router.get("/{id}/facturas", response_model=list[ContratoFacturaOut])
def list_facturas(
    id: int,
    tipo: str | None = Query(None, description="'solenium' o 'inversionista'"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    q = db.query(ContratoFactura).filter(ContratoFactura.contrato_id == id)
    if tipo:
        q = q.filter(ContratoFactura.tipo == tipo)
    return q.order_by(ContratoFactura.fecha.desc()).all()


@router.post("/{id}/facturas", response_model=ContratoFacturaOut, status_code=201)
def create_factura(
    id: int,
    data: ContratoFacturaCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_or_404(id, db)
    factura = ContratoFactura(contrato_id=id, **data.model_dump())
    db.add(factura)
    db.commit()
    db.refresh(factura)
    return factura


@router.patch("/{id}/facturas/{factura_id}", response_model=ContratoFacturaOut)
def update_factura(
    id: int,
    factura_id: int,
    data: ContratoFacturaUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    factura = db.query(ContratoFactura).filter(ContratoFactura.id == factura_id, ContratoFactura.contrato_id == id).first()
    if not factura:
        raise HTTPException(404, "Factura no encontrada")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(factura, k, v)
    db.commit()
    db.refresh(factura)
    return factura


@router.delete("/{id}/facturas/{factura_id}", status_code=204)
def delete_factura(
    id: int,
    factura_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    factura = db.query(ContratoFactura).filter(ContratoFactura.id == factura_id, ContratoFactura.contrato_id == id).first()
    if not factura:
        raise HTTPException(404, "Factura no encontrada")
    db.delete(factura)
    db.commit()


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
