import os
import uuid
from datetime import date, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente, ClienteServicio, ClienteDocumentoComercial
from app.schemas.clientes import (
    ClienteCreate, ClienteUpdate, ClienteOut, ClienteListOut,
    ClienteServicioCreate, ClienteServicioOut,
    ClienteDocumentoCreate, ClienteDocumentoUpdate, ClienteDocumentoOut,
)
from app.schemas.client_kpis import ClienteKPIsOut
from app.schemas.common import PaginatedResponse

UPLOADS_DIR = Path("uploads/clientes")
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

router = APIRouter(prefix="/clientes", tags=["Clientes"])


# ── KPIs del panel de resumen (funciones puras, testeables sin DB) ────────────

# Orden de severidad del semáforo PPA: el peor estado gana al agregar contratos.
_PPA_STATUS_ORDER = {"Green": 0, "Yellow": 1, "Red": 2}


def _previous_complete_month(today: date) -> date:
    """Primer día del último mes calendario *completo*.

    Si hoy es junio 2026 → date(2026, 5, 1). Se usa porque `liquidaciones.periodo`
    almacena siempre el primer día del mes.
    """
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    return last_of_prev.replace(day=1)


def _kwh_to_mwh(total_kwh) -> float:
    """Convierte kWh→MWh con 3 decimales; None/0 → 0.0."""
    if not total_kwh:
        return 0.0
    return round(float(total_kwh) / 1000.0, 3)


def _ppa_status_for_contract(*, fecha_fin, gen_mwh, compromiso_mwh, today: date) -> str:
    """Semáforo de UN contrato PPA. El peor de dos dimensiones de riesgo gana:

    - Vencimiento (`fecha_fin`): ya vencido o <1 mes → Red; <6 meses → Yellow;
      en otro caso (o sin fecha) → Green.
    - Entrega vs compromiso (último `cumplimiento_mensual`): ratio<0.9 → Red;
      0.9≤ratio<1.0 → Yellow; ≥1.0 → Green.

    Un contrato sin señales de riesgo (sin fecha_fin y sin compromiso medido)
    se considera 'Green' (existe, pero no hay riesgo conocido).
    """
    statuses: list[str] = []

    if fecha_fin is not None:
        days = (fecha_fin - today).days
        if days < 30:
            statuses.append("Red")
        elif days < 182:
            statuses.append("Yellow")
        else:
            statuses.append("Green")

    if compromiso_mwh and compromiso_mwh > 0 and gen_mwh is not None:
        ratio = gen_mwh / compromiso_mwh
        if ratio < 0.9:
            statuses.append("Red")
        elif ratio < 1.0:
            statuses.append("Yellow")
        else:
            statuses.append("Green")

    if not statuses:
        return "Green"
    return max(statuses, key=lambda s: _PPA_STATUS_ORDER[s])


def _aggregate_ppa_status(statuses: list[str]) -> str:
    """Combina los semáforos por contrato → uno solo. Sin contratos → 'N/A'."""
    valid = [s for s in statuses if s in _PPA_STATUS_ORDER]
    if not valid:
        return "N/A"
    return max(valid, key=lambda s: _PPA_STATUS_ORDER[s])


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


@router.post("", response_model=ClienteOut, status_code=201)
def create_cliente(data: ClienteCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
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
    db.delete(cliente)
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
    """List all projects where this client is owner or investor."""
    from app.models.proyectos import Proyecto, ProyectoInversionista
    _get_cliente_or_404(id, db)

    # Projects where client is owner
    owned = db.query(Proyecto).filter(
        Proyecto.cliente_id == id,
        Proyecto.deleted_at.is_(None),
    ).all()

    # Projects where client is investor
    invested_ids = (
        db.query(ProyectoInversionista.proyecto_id)
        .filter(ProyectoInversionista.cliente_id == id)
        .all()
    )
    invested_project_ids = {r[0] for r in invested_ids} - {p.id for p in owned}
    invested = (
        db.query(Proyecto)
        .filter(Proyecto.id.in_(invested_project_ids), Proyecto.deleted_at.is_(None))
        .all()
    ) if invested_project_ids else []

    def _proj(p, rol):
        return {
            "id": p.id,
            "nombre_comercial": p.nombre_comercial,
            "estado": p.estado.value if hasattr(p.estado, "value") else p.estado,
            "potencia_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
            "departamento": p.departamento,
            "municipio": p.municipio,
            "rol": rol,
        }

    return [_proj(p, "propietario") for p in owned] + [_proj(p, "inversionista") for p in invested]


@router.get("/{id}/fronteras")
def list_client_fronteras(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """List fronteras linked to this client via their projects."""
    from app.models.proyectos import Proyecto, ProyectoInversionista
    from app.models.fronteras import Frontera
    _get_cliente_or_404(id, db)

    # Gather all project IDs for this client (owned + invested)
    owned_ids = (
        db.query(Proyecto.id)
        .filter(Proyecto.cliente_id == id, Proyecto.deleted_at.is_(None))
        .all()
    )
    invested_ids = (
        db.query(ProyectoInversionista.proyecto_id)
        .filter(ProyectoInversionista.cliente_id == id)
        .all()
    )
    all_project_ids = {r[0] for r in owned_ids} | {r[0] for r in invested_ids}
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


# ── Panel de resumen (KPIs) ───────────────────────────────────────────────────

@router.get("/{id}/resumen", response_model=ClienteKPIsOut)
def get_cliente_resumen(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """KPIs operativos y financieros del cliente para el panel de resumen.

    - **MWh netos (mes anterior):** energía entregada (suma de `energia_kwh` de los
      datos XM de las liquidaciones del último mes completo) de los proyectos del cliente.
    - **Servicios activos:** proyectos del cliente en operación.
    - **Cumplimiento PPA:** semáforo derivado del vencimiento de los contratos PPA y de
      la entrega vs. compromiso del último `cumplimiento_mensual` (peor estado gana).
    """
    from sqlalchemy import func, or_
    from app.models.proyectos import Proyecto
    from app.models.liquidaciones import Liquidacion, LiquidacionXMDato
    from app.models.contratos import PPAContrato
    from app.models.cumplimiento import CumplimientoMensual

    _get_cliente_or_404(id, db)

    today = date.today()
    periodo_start = _previous_complete_month(today)

    # MWh netos del mes anterior. La constraint uq_liquidacion_proyecto_periodo
    # garantiza una sola liquidación por (proyecto, periodo), así que sumar los
    # datos XM no duplica energía entre liquidaciones del mismo periodo.
    total_kwh = (
        db.query(func.coalesce(func.sum(LiquidacionXMDato.energia_kwh), 0))
        .join(Liquidacion, LiquidacionXMDato.liquidacion_id == Liquidacion.id)
        .join(Proyecto, Liquidacion.proyecto_id == Proyecto.id)
        .filter(
            Proyecto.cliente_id == id,
            Proyecto.deleted_at.is_(None),
            Liquidacion.deleted_at.is_(None),
            Liquidacion.periodo == periodo_start,
        )
        .scalar()
    )
    mwh_net = _kwh_to_mwh(total_kwh)

    # Servicios activos = proyectos en operación
    active_services = (
        db.query(func.count(Proyecto.id))
        .filter(
            Proyecto.cliente_id == id,
            Proyecto.deleted_at.is_(None),
            Proyecto.estado == "en_operacion",
        )
        .scalar()
    ) or 0

    # Cumplimiento PPA (semáforo)
    contratos = (
        db.query(PPAContrato)
        .filter(
            PPAContrato.deleted_at.is_(None),
            or_(PPAContrato.comprador_id == id, PPAContrato.vendedor_id == id),
        )
        .all()
    )
    statuses: list[str] = []
    for c in contratos:
        ultimo = (
            db.query(CumplimientoMensual)
            .filter(CumplimientoMensual.contrato_ppa_id == c.id)
            .order_by(CumplimientoMensual.anio.desc(), CumplimientoMensual.mes.desc())
            .first()
        )
        gen = float(ultimo.gen_total_mwh) if ultimo and ultimo.gen_total_mwh is not None else None
        comp = float(ultimo.compromiso_mwh) if ultimo and ultimo.compromiso_mwh is not None else None
        statuses.append(_ppa_status_for_contract(
            fecha_fin=c.fecha_fin, gen_mwh=gen, compromiso_mwh=comp, today=today,
        ))

    return ClienteKPIsOut(
        mwh_net_last_month=mwh_net,
        active_services_count=int(active_services),
        ppa_compliance_status=_aggregate_ppa_status(statuses),
        periodo=periodo_start.strftime("%Y-%m"),
        ppa_contracts_count=len(contratos),
    )
