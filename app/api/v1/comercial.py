"""CRM comercial: pipeline Prospección→Oferta→Negociación→Fin.

Capa PREVIA a operación — reutiliza Cliente/Proyecto/Contactos/Documentos
existentes. Solo roles admin y comercial (lectura y escritura).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.operadores_red import OperadorRed
from app.models.comercial import Oportunidad, OportunidadEstadoHistorial, OportunidadGestion
from app.schemas.comercial import (
    OportunidadCreate, OportunidadUpdate, EstadoChangeIn, GestionCreate, ProyectoDesdeCRMIn,
)
from app.services.comercial import calcular_alerta, col_now

router = APIRouter(prefix="/comercial", tags=["comercial"])


def _check_comercial(current: Usuario):
    if current.rol.value not in ("admin", "comercial"):
        raise HTTPException(403, "Requiere rol comercial o admin")


def _get_oportunidad_or_404(id: int, db: Session) -> Oportunidad:
    op = (
        db.query(Oportunidad)
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    return op


def _proyecto_out(p: Proyecto) -> dict:
    return {
        "id": p.id,
        "nombre_comercial": p.nombre_comercial,
        "potencia_instalada_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
        "departamento": p.departamento,
        "municipio": p.municipio,
        "operador_red": p.operador_red,
        "operador_red_id": p.operador_red_id,
        "estado": p.estado if isinstance(p.estado, str) else p.estado.value,
        "fecha_estimada_energizacion": p.fecha_estimada_energizacion,
        "fecha_inicio_comercializacion": p.fecha_inicio_comercializacion,
        "mwh_mes_estimado": float(p.mwh_mes_estimado) if p.mwh_mes_estimado is not None else None,
    }


def _op_base_out(op: Oportunidad, cliente: Cliente, ultima_gestion, ahora: datetime) -> dict:
    estado = op.estado if isinstance(op.estado, str) else op.estado.value
    dias, alerta = calcular_alerta(estado, op.estado_desde, ultima_gestion,
                                   settings.COMERCIAL_ALERTA_DIAS, ahora)
    return {
        "id": op.id,
        "nombre": op.nombre or cliente.razon_social_nombre,
        "cliente_id": op.cliente_id,
        "cliente_razon_social": cliente.razon_social_nombre,
        "cliente_nit": cliente.nit_cedula,
        "tipo_servicio": op.tipo_servicio if isinstance(op.tipo_servicio, (str, type(None))) else op.tipo_servicio.value,
        "estado": estado,
        "estado_desde": op.estado_desde,
        "numero_oferta": op.numero_oferta,
        "es_migrada": op.es_migrada,
        "dias_sin_respuesta": dias,
        "alerta": alerta,
        "ultima_gestion_fecha": ultima_gestion,
    }


@router.get("/config")
def get_config(_=Depends(get_current_user)):
    return {"alerta_dias": settings.COMERCIAL_ALERTA_DIAS}


@router.get("/oportunidades")
def list_oportunidades(
    estado: str | None = Query(None),
    tipo_servicio: str | None = Query(None),
    cliente_id: int | None = Query(None),
    q: str | None = Query(None),
    solo_alerta: bool = Query(False),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    ult_sq = (
        db.query(OportunidadGestion.oportunidad_id.label("oid"),
                 func.max(OportunidadGestion.fecha).label("ultima"))
        .group_by(OportunidadGestion.oportunidad_id).subquery()
    )
    proy_sq = (
        db.query(Proyecto.oportunidad_id.label("oid"),
                 func.count(Proyecto.id).label("n"),
                 func.coalesce(func.sum(Proyecto.potencia_instalada_kwp), 0).label("kwp"))
        .filter(Proyecto.deleted_at.is_(None), Proyecto.oportunidad_id.isnot(None))
        .group_by(Proyecto.oportunidad_id).subquery()
    )
    qy = (
        db.query(Oportunidad, Cliente, ult_sq.c.ultima, proy_sq.c.n, proy_sq.c.kwp)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id)
        .outerjoin(ult_sq, ult_sq.c.oid == Oportunidad.id)
        .outerjoin(proy_sq, proy_sq.c.oid == Oportunidad.id)
        .filter(Oportunidad.deleted_at.is_(None), Cliente.deleted_at.is_(None))
    )
    if estado:
        qy = qy.filter(Oportunidad.estado == estado)
    if tipo_servicio:
        qy = qy.filter(Oportunidad.tipo_servicio == tipo_servicio)
    if cliente_id:
        qy = qy.filter(Oportunidad.cliente_id == cliente_id)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(
            Oportunidad.nombre.ilike(like) | Cliente.razon_social_nombre.ilike(like)
        )
    ahora = col_now()
    out = []
    for op, cli, ultima, n_proy, kwp in qy.order_by(Oportunidad.updated_at.desc()).all():
        row = _op_base_out(op, cli, ultima, ahora)
        row["num_proyectos"] = int(n_proy or 0)
        row["capacidad_total_kwp"] = float(kwp or 0)
        if solo_alerta and not row["alerta"]:
            continue
        out.append(row)
    return out


@router.post("/oportunidades", status_code=201)
def create_oportunidad(
    data: OportunidadCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    if data.cliente_id:
        cliente = (
            db.query(Cliente)
            .filter(Cliente.id == data.cliente_id, Cliente.deleted_at.is_(None))
            .first()
        )
        if not cliente:
            raise HTTPException(422, "Cliente no encontrado")
    else:
        cn = data.cliente_nuevo
        cliente = Cliente(
            razon_social_nombre=cn.razon_social_nombre,
            nit_cedula=cn.nit_cedula or None,
            origen_tipo=cn.origen_tipo,
            origen_detalle=cn.origen_detalle,
        )
        db.add(cliente)
        db.flush()  # asigna cliente.id sin cerrar la transacción
        for c in cn.contactos:
            db.add(Contacto(cliente_id=cliente.id, nombre=c.nombre,
                            telefono=c.telefono, email=c.email, tipo=c.tipo))

    op = Oportunidad(
        cliente_id=cliente.id,
        nombre=data.nombre,
        tipo_servicio=data.tipo_servicio,
        notas=data.notas,
        estado="prospeccion",          # SIEMPRE server-side (spec §3.1)
        estado_desde=col_now(),
        creado_por_usuario_id=current.id,
    )
    db.add(op)
    db.flush()
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=op.id, estado_anterior=None,
        estado_nuevo="prospeccion", usuario_id=current.id))
    db.commit()
    db.refresh(op)
    return _op_base_out(op, cliente, None, col_now()) | {"num_proyectos": 0, "capacidad_total_kwp": 0.0}


@router.get("/oportunidades/{id}")
def get_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    op = (
        db.query(Oportunidad)
        .options(
            selectinload(Oportunidad.cliente).selectinload(Cliente.contactos),
            selectinload(Oportunidad.proyectos),
            selectinload(Oportunidad.gestiones),
            selectinload(Oportunidad.historial),
            selectinload(Oportunidad.documentos),
        )
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    ultima = op.gestiones[0].fecha if op.gestiones else None
    base = _op_base_out(op, op.cliente, ultima, col_now())
    base.update({
        "notas": op.notas,
        "fecha_tentativa_inicio_representacion": op.fecha_tentativa_inicio_representacion,
        "fecha_tentativa_inicio_compra_energia": op.fecha_tentativa_inicio_compra_energia,
        "fecha_estimada_firma": op.fecha_estimada_firma,
        "cliente": {
            "id": op.cliente.id,
            "razon_social_nombre": op.cliente.razon_social_nombre,
            "nit_cedula": op.cliente.nit_cedula,
            "origen_tipo": op.cliente.origen_tipo,
            "origen_detalle": op.cliente.origen_detalle,
        },
        "proyectos": [_proyecto_out(p) for p in op.proyectos if p.deleted_at is None],
        "documentos": [
            {"id": d.id, "tipo": d.tipo if isinstance(d.tipo, str) else d.tipo.value,
             "nombre": d.nombre, "numero": d.numero,
             "estado": d.estado if isinstance(d.estado, str) else d.estado.value,
             "archivo_url": d.archivo_url, "archivo_nombre": d.archivo_nombre,
             "fecha": d.fecha}
            for d in op.documentos
        ],
        "gestiones": [
            {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
             "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id}
            for g in op.gestiones
        ],
        "historial": [
            {"id": h.id, "estado_anterior": h.estado_anterior,
             "estado_nuevo": h.estado_nuevo, "fecha": h.created_at,
             "usuario_id": h.usuario_id}
            for h in op.historial
        ],
    })
    return base


@router.patch("/oportunidades/{id}")
def update_oportunidad(
    id: int, data: OportunidadUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(op, k, v)
    db.commit()
    return {"ok": True, "id": op.id}


@router.delete("/oportunidades/{id}", status_code=204)
def delete_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin puede eliminar oportunidades")
    op = _get_oportunidad_or_404(id, db)
    # Los proyectos NO se borran: se desvinculan (spec §7).
    db.query(Proyecto).filter(Proyecto.oportunidad_id == id).update({"oportunidad_id": None})
    op.deleted_at = col_now()
    db.commit()


@router.post("/oportunidades/{id}/estado")
def cambiar_estado(
    id: int, data: EstadoChangeIn,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    actual = op.estado if isinstance(op.estado, str) else op.estado.value
    if data.estado == actual:
        raise HTTPException(409, f"La oportunidad ya está en '{actual}'")
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=op.id, estado_anterior=actual,
        estado_nuevo=data.estado, usuario_id=current.id))
    op.estado = data.estado
    op.estado_desde = col_now()
    db.commit()
    return {"ok": True, "estado": data.estado, "estado_desde": op.estado_desde}


@router.get("/oportunidades/{id}/gestiones")
def list_gestiones(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    gs = (
        db.query(OportunidadGestion)
        .filter(OportunidadGestion.oportunidad_id == id)
        .order_by(OportunidadGestion.fecha.desc())
        .all()
    )
    return [
        {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
         "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id}
        for g in gs
    ]


@router.post("/oportunidades/{id}/gestiones", status_code=201)
def add_gestion(
    id: int, data: GestionCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    g = OportunidadGestion(
        oportunidad_id=id, tipo=data.tipo, descripcion=data.descripcion,
        fecha=data.fecha or col_now(), usuario_id=current.id)
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "tipo": data.tipo, "descripcion": g.descripcion, "fecha": g.fecha}


@router.post("/oportunidades/{id}/proyectos", status_code=201)
def add_proyecto(
    id: int, data: ProyectoDesdeCRMIn,
    forzar: bool = Query(False, description="true: crear aunque exista un nombre muy parecido"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Agregar proyecto desde el CRM. El proyecto creado ES un Proyecto normal
    de la plataforma (misma tabla); solo queda vinculado a la oportunidad.
    Validación bloqueante: operador de red obligatorio y del catálogo."""
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    operador = db.query(OperadorRed).filter(OperadorRed.id == data.operador_red_id).first()
    if not operador:
        raise HTTPException(422, "Debes seleccionar un operador de red válido del catálogo")

    # Mismo aviso de duplicado por nombre que el POST /proyectos general.
    from app.api.v1.proyectos import _buscar_duplicado_por_nombre
    if not forzar:
        duplicado = _buscar_duplicado_por_nombre(db, data.nombre_comercial)
        if duplicado:
            raise HTTPException(409, {
                "codigo": "posible_duplicado",
                "mensaje": f"Ya existe un proyecto con nombre parecido: {duplicado.nombre_comercial}",
                "proyecto_id": duplicado.id,
            })

    p = Proyecto(
        nombre_comercial=data.nombre_comercial,
        potencia_instalada_kwp=data.potencia_instalada_kwp,
        departamento=data.departamento,
        municipio=data.municipio,
        operador_red_id=operador.id,
        # Sincroniza el texto legacy para que las vistas viejas lo muestren.
        operador_red=operador.nombre_comercial or operador.nombre_legal,
        oportunidad_id=id,
        origen="manual",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proyecto_out(p)


@router.post("/backfill")
def backfill(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Migración inicial: 1 oportunidad en 'fin' por cliente existente sin
    oportunidad, vinculando sus proyectos (vía ProyectoInversionista — la
    misma relación que usa GET /clientes/{id}/proyectos). Idempotente."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")

    con_oportunidad = {
        cid for (cid,) in db.query(Oportunidad.cliente_id)
        .filter(Oportunidad.deleted_at.is_(None)).distinct().all()
    }
    clientes = (
        db.query(Cliente).filter(Cliente.deleted_at.is_(None))
        .order_by(Cliente.id).all()
    )
    a_migrar = [c for c in clientes if c.id not in con_oportunidad]

    resumen = {"clientes_a_migrar": len(a_migrar), "proyectos_a_vincular": 0, "detalle": []}
    ahora = col_now()
    for c in a_migrar:
        proyecto_ids = [
            pid for (pid,) in (
                db.query(ProyectoInversionista.proyecto_id)
                .join(Proyecto, Proyecto.id == ProyectoInversionista.proyecto_id)
                .filter(ProyectoInversionista.cliente_id == c.id,
                        Proyecto.deleted_at.is_(None),
                        Proyecto.oportunidad_id.is_(None))
                .distinct().all()
            )
        ]
        resumen["proyectos_a_vincular"] += len(proyecto_ids)
        resumen["detalle"].append({"cliente_id": c.id, "razon_social": c.razon_social_nombre,
                                   "proyectos": len(proyecto_ids)})
        if not dry_run:
            op = Oportunidad(cliente_id=c.id, estado="fin", estado_desde=ahora,
                             es_migrada=True, creado_por_usuario_id=current.id)
            db.add(op)
            db.flush()
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=op.id, estado_anterior=None,
                estado_nuevo="fin", usuario_id=current.id))
            if proyecto_ids:
                db.query(Proyecto).filter(Proyecto.id.in_(proyecto_ids)).update(
                    {"oportunidad_id": op.id}, synchronize_session=False)
    if not dry_run:
        db.commit()
    resumen["dry_run"] = dry_run
    return resumen
