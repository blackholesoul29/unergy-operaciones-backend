import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente, ClienteDocumentoComercial
from app.models.clientes import ClienteTasaServicio
from app.models.contactos import Contacto, ProyectoAreaContacto
from app.schemas.clientes import (
    ClienteCreate, ClienteUpdate, ClienteOut, ClienteListOut,
    ClienteDocumentoCreate, ClienteDocumentoUpdate, ClienteDocumentoOut,
    TasaServicioUpsert, TasaServicioOut,
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
    servs = servicios_por_cliente(db, ids, plantas=proys)
    alertas = alerta_contratos_por_cliente(db, ids, hoy, plantas=proys)
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
    payload = data.model_dump(exclude={"contactos"})
    cliente = Cliente(**payload)
    db.add(cliente)
    try:
        db.flush()  # asigna cliente.id sin cerrar la transacción -- el UNIQUE de nit_cedula se valida aquí
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un cliente con ese NIT/cédula.")
    for c in data.contactos:
        db.add(Contacto(cliente_id=cliente.id, nombre=c.nombre, telefono=c.telefono,
                         email=c.email, tipo=c.tipo))
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


# Tablas con FK a clientes.id en NO ACTION (sin relationship de cascada en el
# modelo) que de verdad deben BLOQUEAR el borrado -- representan una relación
# de negocio real, no solo un log. auditoría de Clientes 2026-08-28: antes de
# esto, el único mensaje posible asumía siempre "es inversionista de un
# proyecto", aunque en realidad lo bloqueara una Oportunidad (mensaje
# incorrecto para ese caso). email_envios (otro NO ACTION real, un log de
# correos sin ninguna relación de negocio) se corrigió aparte a SET NULL
# (migración 120) -- no debía bloquear nunca.
_TABLAS_BLOQUEAN_BORRADO_CLIENTE = [
    ("proyecto_inversionistas", "cliente_id", "es inversionista de uno o más proyectos"),
    ("oportunidades", "cliente_id", "tiene una o más oportunidades comerciales registradas"),
]


def _motivo_bloqueo_borrado_cliente(db: Session, id: int) -> str | None:
    for tabla, columna, motivo in _TABLAS_BLOQUEAN_BORRADO_CLIENTE:
        existe = db.execute(
            text(f"SELECT 1 FROM {tabla} WHERE {columna} = :id LIMIT 1"), {"id": id}
        ).first()
        if existe:
            return motivo
    return None


@router.delete("/{id}", status_code=204)
def delete_cliente(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    # deleted_at IS NULL: un cliente ya borrado se ve como "no encontrado", igual
    # que en el resto de la API (~14 sitios filtran por esto).
    cliente = db.query(Cliente).filter(Cliente.id == id, Cliente.deleted_at.is_(None)).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")

    motivo = _motivo_bloqueo_borrado_cliente(db, id)
    if motivo:
        raise HTTPException(409, f"No se puede eliminar: este cliente {motivo}. Desvincúlalo primero.")

    # Vínculos inofensivos: punteros de contacto (CGM/operacional/liquidación)
    # que un proyecto tenga apuntando a este cliente. Se limpian igual que antes --
    # el proyecto vuelve a usar sus inversionistas por defecto.
    db.query(ProyectoAreaContacto).filter(ProyectoAreaContacto.cliente_id == id).delete()

    # Soft-delete, nunca físico -- auditoría de Clientes 2026-08-28: era el único
    # borrado físico de Cliente en toda la API, inconsistente con merge_clientes/
    # dedup_clientes (documentan explícitamente "nunca borra físico") y con los
    # ~14 sitios que ya filtran por deleted_at IS_(None). Por objeto (no raw SQL)
    # para que audit.py sí lo vea -- ver tests/test_escrituras_masivas.py. Un
    # efecto colateral bueno: contactos/servicios/documentos ya no se pierden
    # (el cascade="all, delete-orphan" solo dispara con un delete físico), así
    # que restaurar deleted_at a NULL deja al cliente exactamente como estaba.
    cliente.deleted_at = datetime.now(timezone.utc)
    db.commit()


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


# ── Excepciones de tasa de impuesto por servicio ──────────────────────────────
@router.get("/{id}/tasas-servicio", response_model=list[TasaServicioOut])
def listar_tasas_servicio(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_cliente_or_404(id, db)
    return (
        db.query(ClienteTasaServicio)
        .filter(ClienteTasaServicio.cliente_id == id)
        .order_by(ClienteTasaServicio.servicio, ClienteTasaServicio.proyecto_id).all()
    )


@router.put("/{id}/tasa-servicio", response_model=TasaServicioOut)
def upsert_tasa_servicio(id: int, data: TasaServicioUpsert,
                         db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Crea/actualiza una excepción de tasa por (cliente, servicio[, proyecto]).
    Cada _pct null hereda la tasa general del cliente."""
    _get_cliente_or_404(id, db)
    row = (
        db.query(ClienteTasaServicio)
        .filter(
            ClienteTasaServicio.cliente_id == id,
            ClienteTasaServicio.servicio == data.servicio,
            ClienteTasaServicio.proyecto_id.is_(data.proyecto_id) if data.proyecto_id is None
            else ClienteTasaServicio.proyecto_id == data.proyecto_id,
        ).first()
    )
    if row is None:
        row = ClienteTasaServicio(cliente_id=id, servicio=data.servicio, proyecto_id=data.proyecto_id)
        db.add(row)
    row.iva_pct = data.iva_pct
    row.retencion_pct = data.retencion_pct
    row.reteiva_pct = data.reteiva_pct
    row.reteica_pct = data.reteica_pct
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{id}/tasa-servicio/{tasa_id}")
def eliminar_tasa_servicio(id: int, tasa_id: int,
                           db: Session = Depends(get_db), _=Depends(get_current_user)):
    db.query(ClienteTasaServicio).filter(
        ClienteTasaServicio.id == tasa_id, ClienteTasaServicio.cliente_id == id
    ).delete()
    db.commit()
    return {"ok": True}


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
    from app.models.proyectos import Proyecto, ProyectoInversionista
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
        .join(Proyecto, Proyecto.id == Frontera.proyecto_id)
        .filter(
            Frontera.proyecto_id.in_(all_project_ids),
            Frontera.deleted_at.is_(None),
            Proyecto.deleted_at.is_(None),
        )
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


# ── Servicios derivados de los contratos de las plantas ──────────────────────

@router.get("/{id}/servicios-contratos")
def list_client_servicios_contratos(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
    hoy: date | None = None,  # inyectable en tests
):
    """Servicios que Unergy le presta a este cliente, DERIVADOS de los contratos
    de servicio reales de sus plantas.

    "Plantas del cliente" = misma unión que usa el panel 360 (inversionista +
    contratante de un contrato de servicio + comprador/vendedor de un PPA). Toma
    TODOS los `contratos_servicio` sobre esas plantas -- el contratante del
    contrato puede estar vacío o ser Unergy; lo que importa es que el contrato
    está sobre una planta del cliente. Caso real: Quantum es inversionista de GD
    Sirius y GD Elektra, cuyos contratos de representación no lo tienen como
    contratante. Los agrupa por tipo de servicio, cada uno con sus plantas,
    semáforo de vencimiento y link al contrato en Drive, para encontrar el
    contrato buscando por cliente y no solo por planta. Solo lectura."""
    from collections import defaultdict
    from sqlalchemy import or_
    from app.models.contratos import ContratoServicio
    from app.models.proyectos import Proyecto
    from app.services.clientes_panel import (
        peor_semaforo, proyectos_por_cliente, semaforo_contrato,
    )

    hoy = hoy or date.today()
    _get_cliente_or_404(id, db)

    plant_ids = proyectos_por_cliente(db, {id}).get(id, set())
    condiciones = []
    if plant_ids:
        condiciones.append(ContratoServicio.proyecto_id.in_(plant_ids))
    condiciones.append(ContratoServicio.contratante_id == id)  # por si contrata sin planta ligada
    condiciones.append(ContratoServicio.prestador_id == id)  # por si presta sin planta ligada
    contratos = (
        db.query(ContratoServicio)
        .options(selectinload(ContratoServicio.documentos_comerciales))  # lo lee `enlace_drive` abajo
        .filter(or_(*condiciones))
        .all()
    )
    if not contratos:
        return []

    proyecto_ids = {c.proyecto_id for c in contratos if c.proyecto_id}
    proyectos = {
        p.id: p for p in db.query(Proyecto)
        .filter(Proyecto.id.in_(proyecto_ids), Proyecto.deleted_at.is_(None)).all()
    } if proyecto_ids else {}

    def _enum_val(v):
        return v.value if hasattr(v, "value") else v

    def _num(v):
        return float(v) if v is not None else None

    def _fecha(v):
        return v.isoformat() if v else None

    def _tarifa(c):
        """La tarifa relevante según el tipo de servicio del contrato."""
        serv = _enum_val(c.servicio_aplica)
        if serv == "representacion":
            return _num(c.tarifa_representacion)
        if serv == "cgm":
            return _num(c.tarifa_cgm)
        if serv == "promotor":
            return _num(c.promotor_tarifa)
        return _num(c.tarifa_base)

    grupos: dict[str, list] = defaultdict(list)
    for c in contratos:
        serv = _enum_val(c.servicio_aplica)
        estado = _enum_val(c.estado)
        grupos[serv].append({
            "contrato_id": c.id,
            "proyecto_id": c.proyecto_id,
            "proyecto_nombre": proyectos[c.proyecto_id].nombre_comercial
                               if c.proyecto_id in proyectos else None,
            "numero_contrato": c.numero_contrato,
            "fecha_inicio": _fecha(c.fecha_inicio),
            "fecha_fin": _fecha(c.fecha_fin),
            "estado": estado,
            "semaforo": "vencido" if estado == "terminado"
                        else semaforo_contrato(c.fecha_fin, hoy),
            "renovacion_automatica": c.renovacion_automatica,
            "tarifa": _tarifa(c),
            "enlace_drive": c.enlace_drive,
        })

    salida = []
    for serv, filas in grupos.items():
        filas.sort(key=lambda x: (x["fecha_fin"] is None, x["fecha_fin"] or ""))
        proyectos_distintos = {f["proyecto_id"] for f in filas if f["proyecto_id"]}
        salida.append({
            "servicio": serv,
            "num_plantas": len(proyectos_distintos),
            "num_contratos": len(filas),
            "semaforo": peor_semaforo([f["semaforo"] for f in filas]),
            "contratos": filas,
        })
    salida.sort(key=lambda g: g["servicio"])
    return salida


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
        peor_semaforo, proyectos_por_cliente, renovacion_combinada, semaforo_contrato,
    )
    from app.schemas.clientes import ClienteOut

    hoy = hoy or date.today()
    cliente = _get_cliente_or_404(id, db)

    # contratante_id/prestador_id casi nunca se pobla en la práctica (el campo
    # del wizard es texto libre); mismo fallback que list_client_servicios_contratos
    # -- también por planta del cliente (inversionista/contratante/PPA), no solo
    # por el ID directo en el contrato. Sin esto, "condiciones económicas" y
    # buena parte de "contratos" del panel 360 quedaban vacíos siempre.
    plant_ids = proyectos_por_cliente(db, {id}).get(id, set())
    condiciones_filtro = [ContratoServicio.contratante_id == id, ContratoServicio.prestador_id == id]
    if plant_ids:
        condiciones_filtro.append(ContratoServicio.proyecto_id.in_(plant_ids))
    contratos_serv = (
        db.query(ContratoServicio)
        .options(selectinload(ContratoServicio.documentos_comerciales))  # lo lee `enlace_drive` abajo
        .filter(or_(*condiciones_filtro))
        .all()
    )
    ppas = (
        db.query(PPAContrato)
        .options(selectinload(PPAContrato.proyectos),
                 selectinload(PPAContrato.documentos_comerciales))  # lo lee `carpeta_link` abajo
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
    servicios_kpi = sorted({x["tipo"] for x in contratos})
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


# ── Fusión de clientes duplicados ───────────────────────────────────────────
# Mismo patrón que /proyectos/{ganador_id}/merge/{perdedor_id}: dry_run por
# defecto, mueve filas relacionadas, resuelve colisiones quedandose con la del
# ganador, y NUNCA borra fisico -- soft-delete (deleted_at), igual que ya hace
# dedup_clientes (reversible).

_MERGE_CLIENTE_SIMPLE = ["cliente_documentos_comerciales", "oportunidades", "proyecto_area_contacto"]
_MERGE_CLIENTE_COMPOSITE = [
    ("contactos", ["email", "tipo"]),                  # UNIQUE (cliente_id, email, tipo)
    ("proyecto_inversionistas", ["proyecto_id"]),       # evita duplicar al cliente como inversionista del mismo proyecto
]
# nit_cedula es UNIQUE en la BD -- necesita liberarse en el perdedor antes de
# copiarse al ganador (mismo tratamiento que sunfactory_project_id en proyectos).
_MERGE_CLIENTE_SCALAR_UNIQUE = ["nit_cedula"]
_MERGE_CLIENTE_SCALAR_FILL_IF_EMPTY = [
    "direccion", "ciudad", "departamento",
    "tipo_persona", "representante_legal",
]


def _scalar_cliente(db: Session, sql: str, params: dict):
    return db.execute(text(sql), params).scalar()


@router.post("/{ganador_id}/merge/{perdedor_id}")
def merge_clientes(
    ganador_id: int,
    perdedor_id: int,
    dry_run: bool = Query(True, description="true (default): solo reporta, no modifica nada."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Fusiona el cliente `perdedor_id` dentro de `ganador_id`.

    Con `dry_run=true` (por defecto) solo devuelve un reporte de lo que pasaría.
    Con `dry_run=false` ejecuta la fusión completa en una sola transacción y da
    de baja (soft-delete) al perdedor. Política de colisión: se conserva la
    fila del ganador.
    """
    if ganador_id == perdedor_id:
        raise HTTPException(400, "El ganador y el perdedor no pueden ser el mismo cliente.")
    ganador = db.query(Cliente).filter(Cliente.id == ganador_id, Cliente.deleted_at.is_(None)).first()
    perdedor = db.query(Cliente).filter(Cliente.id == perdedor_id, Cliente.deleted_at.is_(None)).first()
    if not ganador:
        raise HTTPException(404, f"Cliente ganador {ganador_id} no encontrado.")
    if not perdedor:
        raise HTTPException(404, f"Cliente perdedor {perdedor_id} no encontrado.")

    p = {"keeper": ganador_id, "loser": perdedor_id}
    movimientos = []  # filas por tabla: {tabla, a_mover, descartadas_por_colision}

    for t in _MERGE_CLIENTE_SIMPLE:
        n = _scalar_cliente(db, f"SELECT count(*) FROM {t} WHERE cliente_id=:loser", p)
        if n:
            movimientos.append({"tabla": t, "a_mover": n, "descartadas_por_colision": 0})

    for t, keys in _MERGE_CLIENTE_COMPOSITE:
        n = _scalar_cliente(db, f"SELECT count(*) FROM {t} WHERE cliente_id=:loser", p)
        if not n:
            continue
        cond = " AND ".join(f"k.{c} = {t}.{c}" for c in keys)
        coli = _scalar_cliente(
            db,
            f"SELECT count(*) FROM {t} WHERE cliente_id=:loser AND EXISTS "
            f"(SELECT 1 FROM {t} k WHERE k.cliente_id=:keeper AND {cond})",
            p,
        )
        movimientos.append({"tabla": t, "a_mover": n - coli, "descartadas_por_colision": coli})

    # ppa_contratos: doble FK (comprador_id / vendedor_id), sin unicidad por cliente.
    ppa_compra = _scalar_cliente(db, "SELECT count(*) FROM ppa_contratos WHERE comprador_id=:loser", p)
    ppa_venta = _scalar_cliente(db, "SELECT count(*) FROM ppa_contratos WHERE vendedor_id=:loser", p)
    if ppa_compra or ppa_venta:
        movimientos.append({"tabla": "ppa_contratos", "a_mover": ppa_compra + ppa_venta, "descartadas_por_colision": 0})

    # contratos_servicio: triple FK (contratante_id / prestador_id / inversionista_id),
    # tampoco tiene unicidad por cliente -- varios contratos pueden compartir el mismo
    # contratante/prestador/inversionista sin problema. Auditoria de Clientes 2026-08-27:
    # faltaba aca, asi que fusionar un cliente que fuera parte de algun contrato de
    # servicio lo dejaba apuntando al perdedor (ya dado de baja, invisible en la UI).
    cs_contratante = _scalar_cliente(db, "SELECT count(*) FROM contratos_servicio WHERE contratante_id=:loser", p)
    cs_prestador = _scalar_cliente(db, "SELECT count(*) FROM contratos_servicio WHERE prestador_id=:loser", p)
    cs_inversionista = _scalar_cliente(db, "SELECT count(*) FROM contratos_servicio WHERE inversionista_id=:loser", p)
    if cs_contratante or cs_prestador or cs_inversionista:
        movimientos.append({
            "tabla": "contratos_servicio",
            "a_mover": cs_contratante + cs_prestador + cs_inversionista,
            "descartadas_por_colision": 0,
        })

    # Campos escalares vacíos en el ganador: qué se copiaría del perdedor.
    campos_copiados = []
    for f in _MERGE_CLIENTE_SCALAR_UNIQUE + _MERGE_CLIENTE_SCALAR_FILL_IF_EMPTY:
        val_keeper = getattr(ganador, f, None)
        val_loser = getattr(perdedor, f, None)
        if (val_keeper in (None, "")) and (val_loser not in (None, "")):
            campos_copiados.append({"campo": f, "valor": val_loser})

    reporte = {
        "dry_run": dry_run,
        "ganador": {"id": ganador.id, "nombre": ganador.razon_social_nombre},
        "perdedor": {"id": perdedor.id, "nombre": perdedor.razon_social_nombre},
        "movimientos": movimientos,
        "campos_copiados_al_ganador": campos_copiados,
        "total_filas_a_mover": sum(m["a_mover"] for m in movimientos),
        "total_filas_descartadas": sum(m["descartadas_por_colision"] for m in movimientos),
    }

    if dry_run:
        return reporte

    try:
        # 1) ppa_contratos: doble FK
        db.execute(text("UPDATE ppa_contratos SET comprador_id=:keeper WHERE comprador_id=:loser"), p)
        db.execute(text("UPDATE ppa_contratos SET vendedor_id=:keeper WHERE vendedor_id=:loser"), p)

        # 1b) contratos_servicio: triple FK
        db.execute(text("UPDATE contratos_servicio SET contratante_id=:keeper WHERE contratante_id=:loser"), p)
        db.execute(text("UPDATE contratos_servicio SET prestador_id=:keeper WHERE prestador_id=:loser"), p)
        db.execute(text("UPDATE contratos_servicio SET inversionista_id=:keeper WHERE inversionista_id=:loser"), p)

        # 2) Tablas con colisión por clave compuesta: descartar la del perdedor, mover el resto
        for t, keys in _MERGE_CLIENTE_COMPOSITE:
            cond = " AND ".join(f"k.{c} = {t}.{c}" for c in keys)
            db.execute(text(
                f"DELETE FROM {t} WHERE cliente_id=:loser AND EXISTS "
                f"(SELECT 1 FROM {t} k WHERE k.cliente_id=:keeper AND {cond})"), p)
            db.execute(text(f"UPDATE {t} SET cliente_id=:keeper WHERE cliente_id=:loser"), p)

        # 3) Tablas simples
        for t in _MERGE_CLIENTE_SIMPLE:
            db.execute(text(f"UPDATE {t} SET cliente_id=:keeper WHERE cliente_id=:loser"), p)

        # 4) Campos escalares únicos: liberar del perdedor y copiar al ganador si está vacío
        for f in _MERGE_CLIENTE_SCALAR_UNIQUE:
            db.execute(text(f"UPDATE clientes SET {f}=NULL WHERE id=:loser"), p)
        for c in campos_copiados:
            db.execute(
                text(f"UPDATE clientes SET {c['campo']}=:val WHERE id=:keeper"),
                {**p, "val": c["valor"]},
            )

        # 5) Dar de baja al perdedor (soft-delete, nunca fisico)
        db.execute(text("UPDATE clientes SET deleted_at = NOW() WHERE id=:loser"), p)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"La fusión falló y se revirtió por completo: {type(e).__name__}: {e}")

    reporte["ejecutado"] = True
    return reporte
