import os
import uuid
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente, ClienteServicio, ClienteDocumentoComercial
from app.models.contactos import Contacto, ProyectoAreaContacto
from app.schemas.clientes import (
    ClienteCreate, ClienteUpdate, ClienteOut, ClienteListOut,
    ClienteServicioCreate, ClienteServicioOut,
    ClienteDocumentoCreate, ClienteDocumentoUpdate, ClienteDocumentoOut,
)
from app.schemas.proyectos import ContactoCreate, ContactoUpdate, ContactoOut
from app.schemas.common import PaginatedResponse
from app.utils.nombre_matching import mejor_candidato

UPLOADS_DIR = Path("uploads/clientes")
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

router = APIRouter(prefix="/clientes", tags=["Clientes"])


def _get_cliente_or_404(id: int, db: Session) -> Cliente:
    c = db.query(Cliente).options(
        selectinload(Cliente.servicios),
        selectinload(Cliente.documentos_comerciales),
    ).filter(Cliente.id == id).first()
    if not c:
        raise HTTPException(404, "Cliente no encontrado")
    return c


@router.get("", response_model=PaginatedResponse[ClienteListOut])
def list_clientes(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
    q: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(Cliente).filter(Cliente.deleted_at.is_(None))
    if q:
        query = query.filter(Cliente.razon_social_nombre.ilike(f"%{q}%"))
    total = query.count()
    items = query.order_by(Cliente.razon_social_nombre).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.get("/vista-comercial")
def vista_comercial(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    hoy: date | None = None,  # inyectable en tests; en producción siempre None
):
    """Listado completo para la tabla comercial de /clientes: contacto comercial
    (del tipo de contacto 'comercial') + agregados (nº plantas, servicios, alerta
    de vencimiento). Devuelve TODOS los clientes (sin paginar): el volumen es bajo
    y el frontend filtra/ordena client-side para respuesta instantánea."""
    from app.services.clientes_panel import (
        alerta_contratos_por_cliente, contacto_comercial_por_cliente,
        proyectos_por_cliente, servicios_por_cliente,
    )
    hoy = hoy or date.today()
    clientes = (
        db.query(Cliente)
        .filter(Cliente.deleted_at.is_(None))
        .order_by(Cliente.razon_social_nombre)
        .all()
    )
    ids = {c.id for c in clientes}
    proys = proyectos_por_cliente(db, ids)
    servs = servicios_por_cliente(db, ids)
    alertas = alerta_contratos_por_cliente(db, ids, hoy)
    comerciales = contacto_comercial_por_cliente(db, ids)

    filas = []
    for c in clientes:
        alerta = alertas.get(c.id, {})
        venc = alerta.get("proximo_vencimiento")
        com = comerciales.get(c.id, {})
        filas.append({
            "id": c.id,
            "razon_social_nombre": c.razon_social_nombre,
            "nit_cedula": c.nit_cedula,
            "tipo_persona": c.tipo_persona.value if hasattr(c.tipo_persona, "value") else c.tipo_persona,
            "ciudad": c.ciudad,
            "departamento": c.departamento,
            "contacto_comercial_nombre": com.get("nombre"),
            "contacto_comercial_telefono": com.get("telefono"),
            "contacto_comercial_correo": com.get("correo"),
            "contactos_comerciales_extra": com.get("adicionales", 0),
            "num_plantas": len(proys.get(c.id, ())),
            "servicios": sorted(servs.get(c.id, set())),
            "alerta_contrato": alerta.get("alerta"),
            "proximo_vencimiento": venc.isoformat() if venc else None,
        })
    return filas


def buscar_cliente_duplicado(db: Session, razon_social_nombre: str | None, excluir_id: int | None = None) -> Cliente | None:
    """Busca un cliente ya existente con nombre muy parecido (mismo algoritmo de
    tokens+similitud que ya usan proyectos/fronteras -- ver app/utils/nombre_matching.py).

    Deliberadamente permisivo (puede marcar como "parecidos" dos empresas distintas
    que comparten una palabra común): el aviso no bloquea, solo exige confirmar
    "crear de todos modos". Caso real que motivó esto: la migración del CRM creó
    "Quantum" como cliente nuevo cuando ya existía "Quantum Energy Ingenieria S.A.S."
    -- un match exacto de nombre no lo hubiera detectado."""
    if not razon_social_nombre:
        return None
    query = db.query(Cliente).filter(Cliente.deleted_at.is_(None))
    if excluir_id:
        query = query.filter(Cliente.id != excluir_id)
    candidatos = [(c, [c.razon_social_nombre]) for c in query.all()]
    match, _score = mejor_candidato(razon_social_nombre, candidatos)
    return match


@router.post("", response_model=ClienteOut, status_code=201)
def create_cliente(
    data: ClienteCreate,
    forzar: bool = Query(False, description="true: crear igual aunque exista un cliente con nombre muy parecido"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if not forzar:
        duplicado = buscar_cliente_duplicado(db, data.razon_social_nombre)
        if duplicado:
            raise HTTPException(
                409,
                {
                    "mensaje": (
                        f"Ya existe un cliente con un nombre muy parecido: "
                        f"'{duplicado.razon_social_nombre}' (ID {duplicado.id})."
                    ),
                    "duplicado_nombre": True,
                    "candidato_id": duplicado.id,
                    "candidato_nombre": duplicado.razon_social_nombre,
                },
            )
    cliente = Cliente(**data.model_dump())
    db.add(cliente)
    db.commit()
    return _get_cliente_or_404(cliente.id, db)


@router.get("/{id}", response_model=ClienteOut)
def get_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_cliente_or_404(id, db)


@router.patch("/{id}", response_model=ClienteOut)
def update_cliente(id: int, data: ClienteUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cliente = _get_cliente_or_404(id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(cliente, k, v)
    db.commit()
    return _get_cliente_or_404(id, db)


@router.delete("/{id}", status_code=204)
def delete_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")

    # Vínculos inofensivos: punteros de contacto (CGM/operacional/liquidación)
    # que un proyecto tenga apuntando a este cliente. Se borran en cascada --
    # el proyecto simplemente vuelve a usar sus inversionistas por defecto.
    # Contactos/servicios/documentos propios ya cascaden vía relationship().
    # proyecto_inversionistas (participación real) NO se toca: si el cliente
    # es inversionista de un proyecto, el borrado debe seguir bloqueado.
    db.query(ProyectoAreaContacto).filter(ProyectoAreaContacto.cliente_id == id).delete()

    db.delete(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "No se puede eliminar: este cliente es inversionista de uno o más "
            "proyectos. Desvincúlalo primero.",
        )


@router.post("/{id}/test-correo")
def test_correo_operacional(
    id: int,
    body: dict,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Envía un correo de prueba a la dirección indicada para verificar
    que los correos operacionales del cliente están bien configurados.
    body: {"email": "destino@empresa.com"}
    """
    from app.services.email_service import send_test_email
    cliente = _get_cliente_or_404(id, db)
    email = (body.get("email") or "").strip()
    if not email:
        raise HTTPException(400, "Debes indicar el campo 'email'")
    try:
        send_test_email(to_email=email, cliente_nombre=cliente.razon_social_nombre)
        return {"ok": True, "enviado_a": email}
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


# ── Servicios ────────────────────────────────────────────────────────────────

@router.get("/{id}/servicios", response_model=list[ClienteServicioOut])
def list_servicios(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return db.query(ClienteServicio).filter(ClienteServicio.cliente_id == id).all()


@router.post("/{id}/servicios", response_model=ClienteServicioOut, status_code=201)
def add_servicio(id: int, data: ClienteServicioCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    existing = db.query(ClienteServicio).filter_by(cliente_id=id, tipo=data.tipo).first()
    if existing:
        raise HTTPException(400, f"El cliente ya tiene el servicio '{data.tipo}' registrado")
    s = ClienteServicio(cliente_id=id, **data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{id}/servicios/{servicio_id}", status_code=204)
def remove_servicio(id: int, servicio_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(ClienteServicio).filter_by(id=servicio_id, cliente_id=id).first()
    if not s:
        raise HTTPException(404, "Servicio no encontrado")
    db.delete(s)
    db.commit()


# ── Contactos ─────────────────────────────────────────────────────────────────
# Correos reales de esta razón social, por área. Aplican por defecto a todos
# sus proyectos, salvo que un proyecto apunte a otro Cliente para ese mismo
# `tipo` (ver app/services/contactos.py y /proyectos/{id}/area-contactos).

@router.get("/{id}/contactos", response_model=list[ContactoOut])
def list_contactos_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return db.query(Contacto).filter_by(cliente_id=id).all()


@router.post("/{id}/contactos", response_model=ContactoOut, status_code=201)
def add_contacto_cliente(id: int, data: ContactoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    c = Contacto(cliente_id=id, **data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.patch("/{id}/contactos/{c_id}", response_model=ContactoOut)
def update_contacto_cliente(id: int, c_id: int, data: ContactoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contacto).filter_by(id=c_id, cliente_id=id).first()
    if not c:
        raise HTTPException(404, "Contacto no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{id}/contactos/{c_id}", status_code=204)
def delete_contacto_cliente(id: int, c_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Contacto).filter_by(id=c_id, cliente_id=id).first()
    if not c:
        raise HTTPException(404, "Contacto no encontrado")
    db.delete(c)
    db.commit()


# ── Documentos comerciales (ofertas / contratos) ──────────────────────────────

@router.get("/{id}/documentos", response_model=list[ClienteDocumentoOut])
def list_documentos(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return (
        db.query(ClienteDocumentoComercial)
        .filter(ClienteDocumentoComercial.cliente_id == id)
        .order_by(ClienteDocumentoComercial.tipo, ClienteDocumentoComercial.fecha)
        .all()
    )


@router.post("/{id}/documentos", response_model=ClienteDocumentoOut, status_code=201)
def add_documento(id: int, data: ClienteDocumentoCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    doc = ClienteDocumentoComercial(cliente_id=id, **data.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{id}/documentos/{doc_id}", response_model=ClienteDocumentoOut)
def update_documento(id: int, doc_id: int, data: ClienteDocumentoUpdate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{id}/documentos/{doc_id}", status_code=204)
def delete_documento(id: int, doc_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    # Borrar archivo físico si existe
    if doc.archivo_url and doc.archivo_url.startswith("/static/uploads/"):
        ruta = Path(doc.archivo_url.lstrip("/").replace("static/", "", 1))
        if ruta.exists():
            ruta.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


@router.post("/{id}/documentos/{doc_id}/archivo", response_model=ClienteDocumentoOut)
async def upload_archivo_documento(
    id: int,
    doc_id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    doc = db.query(ClienteDocumentoComercial).filter_by(id=doc_id, cliente_id=id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")

    if archivo.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"Tipo de archivo no permitido. Use PDF, JPG o PNG.")

    contenido = await archivo.read()
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(400, "El archivo supera el límite de 20 MB")

    # Borrar archivo anterior si existe
    if doc.archivo_url and doc.archivo_url.startswith("/static/uploads/"):
        ruta_ant = Path(doc.archivo_url.lstrip("/").replace("static/", "", 1))
        ruta_ant.unlink(missing_ok=True)

    # Guardar nuevo archivo
    ext = Path(archivo.filename).suffix.lower() if archivo.filename else ".pdf"
    nombre_guardado = f"{uuid.uuid4().hex}{ext}"
    carpeta = UPLOADS_DIR / str(id)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_nueva = carpeta / nombre_guardado
    ruta_nueva.write_bytes(contenido)

    doc.archivo_url = f"/static/uploads/clientes/{id}/{nombre_guardado}"
    doc.archivo_nombre = archivo.filename or nombre_guardado
    db.commit()
    db.refresh(doc)
    return doc


# ── Fondos de inversión (origina) ────────────────────────────────────────────


@router.get("/{id}/fondos")
def get_client_fund(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Get the investment fund linked to this client (from originabotdb)."""
    cliente = _get_cliente_or_404(id, db)
    if not cliente.origina_investment_id:
        return {"linked": False, "fund": None}

    from app.services.correlation import fetch_origina_investment_detail
    fund = fetch_origina_investment_detail(cliente.origina_investment_id)
    if not fund:
        return {
            "linked": True,
            "origina_investment_id": cliente.origina_investment_id,
            "fund": None,
            "error": "Fondo no encontrado en Origina (puede haber sido eliminado)",
        }

    return {"linked": True, "fund": fund}


# ── Client linking: Proyectos, Fronteras, Contratos PPA ─────────────────────

@router.get("/{id}/proyectos")
def list_client_proyectos(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List all projects where this client is an investor."""
    from app.models.proyectos import Proyecto, ProyectoInversionista
    _get_cliente_or_404(id, db)

    invested_ids = (
        db.query(ProyectoInversionista.proyecto_id)
        .filter(ProyectoInversionista.cliente_id == id)
        .all()
    )
    invested = (
        db.query(Proyecto)
        .filter(Proyecto.id.in_({r[0] for r in invested_ids}), Proyecto.deleted_at.is_(None))
        .all()
    ) if invested_ids else []

    def _proj(p):
        return {
            "id": p.id,
            "nombre_comercial": p.nombre_comercial,
            "estado": p.estado.value if hasattr(p.estado, "value") else p.estado,
            "potencia_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
            "departamento": p.departamento,
            "municipio": p.municipio,
            "rol": "inversionista",
        }

    return [_proj(p) for p in invested]


@router.get("/{id}/fronteras")
def list_client_fronteras(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List fronteras linked to this client via their projects."""
    from app.models.proyectos import ProyectoInversionista
    from app.models.fronteras import Frontera
    _get_cliente_or_404(id, db)

    invested_ids = (
        db.query(ProyectoInversionista.proyecto_id)
        .filter(ProyectoInversionista.cliente_id == id)
        .all()
    )
    all_project_ids = {r[0] for r in invested_ids}
    if not all_project_ids:
        return []

    fronteras = (
        db.query(Frontera)
        .filter(Frontera.proyecto_id.in_(all_project_ids))
        .order_by(Frontera.codigo_frontera)
        .all()
    )
    return [
        {
            "id": f.id,
            "codigo_frontera": f.codigo_frontera,
            "nombre_frontera": f.nombre_frontera,
            "tipo_frontera": f.tipo_frontera.value if hasattr(f.tipo_frontera, "value") else f.tipo_frontera,
            "estado": f.estado.value if hasattr(f.estado, "value") else f.estado,
            "proyecto_id": f.proyecto_id,
        }
        for f in fronteras
    ]


@router.get("/{id}/contratos-ppa")
def list_client_contratos_ppa(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List PPA contracts where this client is buyer or seller."""
    from app.models.contratos import PPAContrato
    from sqlalchemy import or_
    _get_cliente_or_404(id, db)

    contratos = (
        db.query(PPAContrato)
        .filter(
            PPAContrato.deleted_at.is_(None),
            or_(PPAContrato.comprador_id == id, PPAContrato.vendedor_id == id),
        )
        .order_by(PPAContrato.fecha_inicio.desc().nullslast())
        .all()
    )
    return [
        {
            "id": c.id,
            "numero_codigo_contrato": c.numero_codigo_contrato,
            "nombre_interno": c.nombre_interno,
            "comprador_nombre": c.comprador_nombre,
            "vendedor_nombre": c.vendedor_nombre,
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else None,
            "tipo_contrato": c.tipo_contrato,
            "rol": "comprador" if c.comprador_id == id else "vendedor",
        }
        for c in contratos
    ]


# ── Panel 360 del cliente (pestaña Resumen del detalle) ──────────────────────

@router.get("/{id}/panel")
def get_cliente_panel(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    hoy: date | None = None,  # inyectable en tests
):
    """Payload único para la pestaña Resumen del detalle del cliente: KPIs,
    plantas contratadas (fecha fin + renovación), condiciones económicas,
    histórico de participación y contratos (servicio + PPA) con links."""
    from sqlalchemy import or_
    from app.models.contratos import ContratoServicio, PPAContrato
    from app.models.proyectos import Proyecto, ProyectoInversionista
    from app.services.clientes_panel import (
        peor_semaforo, renovacion_combinada, semaforo_contrato,
    )
    from app.schemas.clientes import ClienteOut

    hoy = hoy or date.today()
    cliente = _get_cliente_or_404(id, db)

    contratos_serv = (
        db.query(ContratoServicio)
        .filter(or_(ContratoServicio.contratante_id == id,
                    ContratoServicio.prestador_id == id))
        .all()
    )
    ppas = (
        db.query(PPAContrato)
        .options(selectinload(PPAContrato.proyectos))
        .filter(PPAContrato.deleted_at.is_(None),
                or_(PPAContrato.comprador_id == id, PPAContrato.vendedor_id == id))
        .all()
    )
    participaciones = (
        db.query(ProyectoInversionista)
        .filter(ProyectoInversionista.cliente_id == id)
        .order_by(ProyectoInversionista.proyecto_id, ProyectoInversionista.fecha_inicio)
        .all()
    )

    proyecto_ids = {r.proyecto_id for r in participaciones}
    proyecto_ids |= {c.proyecto_id for c in contratos_serv if c.proyecto_id}
    for ppa in ppas:
        proyecto_ids |= {p.id for p in ppa.proyectos}
    proyectos = {
        p.id: p for p in db.query(Proyecto)
        .filter(Proyecto.id.in_(proyecto_ids), Proyecto.deleted_at.is_(None))
        .all()
    } if proyecto_ids else {}

    def _enum_val(v):
        return v.value if hasattr(v, "value") else v

    def _num(v):
        return float(v) if v is not None else None

    def _fecha(v):
        return v.isoformat() if v else None

    # ── plantas ──
    plantas = []
    for pid, p in sorted(proyectos.items(), key=lambda kv: kv[1].nombre_comercial or ""):
        serv_planta = [c for c in contratos_serv
                       if c.proyecto_id == pid and _enum_val(c.estado) != "terminado"]
        ppa_planta = [c for c in ppas if any(pr.id == pid for pr in c.proyectos)]
        fechas_fin = [c.fecha_fin for c in serv_planta + ppa_planta if c.fecha_fin]
        fecha_fin_contrato = max(fechas_fin) if fechas_fin else None
        renovacion = renovacion_combinada(
            [c.renovacion_automatica for c in serv_planta + ppa_planta]
        )
        servicios_planta = sorted(
            {_enum_val(c.servicio_aplica) for c in serv_planta}
            | ({"ppa"} if ppa_planta else set())
        )
        part_actual = next(
            (_num(r.porcentaje_participacion) for r in participaciones
             if r.proyecto_id == pid and r.porcentaje_participacion is not None
             and (r.fecha_fin is None or r.fecha_fin >= hoy)),
            None,
        )
        semaforos_planta = [semaforo_contrato(c.fecha_fin, hoy)
                            for c in serv_planta + ppa_planta]
        plantas.append({
            "proyecto_id": pid,
            "nombre": p.nombre_comercial,
            "estado": _enum_val(p.estado),
            "potencia_kwp": _num(p.potencia_instalada_kwp),
            "fecha_fin_contrato": _fecha(fecha_fin_contrato),
            "renovacion_automatica": renovacion,
            "servicios": servicios_planta,
            "participacion_actual": part_actual,
            "semaforo": peor_semaforo(semaforos_planta),
        })

    # ── histórico de participación (todas las filas, vigentes y cerradas) ──
    historico = [{
        "proyecto_id": r.proyecto_id,
        "proyecto_nombre": proyectos[r.proyecto_id].nombre_comercial
                           if r.proyecto_id in proyectos else None,
        "fecha_inicio": _fecha(r.fecha_inicio),
        "fecha_fin": _fecha(r.fecha_fin),
        "porcentaje": _num(r.porcentaje_participacion),
    } for r in participaciones]

    # ── condiciones económicas (un renglón por contrato de servicio) ──
    condiciones = [{
        "contrato_id": c.id,
        "proyecto_id": c.proyecto_id,
        "proyecto_nombre": proyectos[c.proyecto_id].nombre_comercial
                           if c.proyecto_id in proyectos else None,
        "servicio": _enum_val(c.servicio_aplica),
        "tarifa_representacion": _num(c.tarifa_representacion),
        "tarifa_cgm": _num(c.tarifa_cgm),
        "tarifa_base": _num(c.tarifa_base),
        "indice_indexacion": c.indice_indexacion,
        "fecha_indexacion": _fecha(c.fecha_indexacion),
    } for c in contratos_serv]

    # ── contratos unificados (servicio + PPA) ──
    contratos = []
    for c in contratos_serv:
        contratos.append({
            "id": c.id,
            "fuente": "servicio",
            "tipo": _enum_val(c.servicio_aplica),
            "numero": c.numero_contrato,
            "proyectos": [proyectos[c.proyecto_id].nombre_comercial]
                          if c.proyecto_id in proyectos else [],
            "fecha_inicio": _fecha(c.fecha_inicio),
            "fecha_fin": _fecha(c.fecha_fin),
            "estado": _enum_val(c.estado),
            "semaforo": "vencido" if _enum_val(c.estado) == "terminado"
                        else semaforo_contrato(c.fecha_fin, hoy),
            "renovacion_automatica": c.renovacion_automatica,
            "link": c.enlace_drive,
        })
    for c in ppas:
        contratos.append({
            "id": c.id,
            "fuente": "ppa",
            "tipo": "ppa",
            "numero": c.numero_codigo_contrato or c.nombre_interno,
            "proyectos": [p.nombre_comercial for p in c.proyectos],
            "fecha_inicio": _fecha(c.fecha_inicio),
            "fecha_fin": _fecha(c.fecha_fin),
            "estado": None,
            "semaforo": semaforo_contrato(c.fecha_fin, hoy),
            "renovacion_automatica": c.renovacion_automatica,
            "link": c.carpeta_link,
        })
    contratos.sort(key=lambda x: (x["fecha_fin"] is None, x["fecha_fin"] or ""))

    # ── KPIs ──
    activos = [x for x in contratos if x["semaforo"] != "vencido"]
    vencimientos = [x["fecha_fin"] for x in activos if x["fecha_fin"]]
    servicios_kpi = sorted({x["tipo"] for x in contratos}
                           | {_enum_val(s.tipo) for s in cliente.servicios})
    kpis = {
        "num_plantas": len(plantas),
        "contratos_activos": len(activos),
        "servicios": servicios_kpi,
        "proximo_vencimiento": min(vencimientos) if vencimientos else None,
    }

    return {
        "cliente": ClienteOut.model_validate(cliente).model_dump(mode="json"),
        "kpis": kpis,
        "plantas": plantas,
        "participaciones_historico": historico,
        "condiciones": condiciones,
        "contratos": contratos,
    }
