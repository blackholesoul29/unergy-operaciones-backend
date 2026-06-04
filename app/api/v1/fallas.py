import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, extract
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import (
    Falla, FallaSeguimiento,
    FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria, FallaCatResolucion,
)
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.schemas.fallas import (
    FallaCreate, FallaUpdate, FallaOut,
    FallaSeguimientoCreate, FallaSeguimientoOut,
    FallaCatalogos, FallaCatEstadoOut, FallaCatPrioridadOut, FallaCatTipoOut, FallaCatResolucionOut,
    FallaSLADashboard, FallaImpacto,
)
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/fallas", tags=["Fallas"])

_SEGS_LOAD = selectinload(Falla.seguimientos).options(
    selectinload(FallaSeguimiento.usuario),
    selectinload(FallaSeguimiento.estado_nuevo),
)

_FALLA_LOAD = [
    selectinload(Falla.proyecto),
    selectinload(Falla.tipo).selectinload(FallaCatTipo.categoria),
    selectinload(Falla.estado),
    selectinload(Falla.prioridad),
    selectinload(Falla.resolucion),
    selectinload(Falla.registrado_por),
    selectinload(Falla.asignado_a),
    _SEGS_LOAD,
]


def _get_or_404(id: int, db: Session) -> Falla:
    falla = db.query(Falla).options(*_FALLA_LOAD).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    return falla


def _gen_codigo(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    max_id = db.query(func.max(Falla.id)).scalar() or 0
    return f"FAL-{year}-{max_id + 1:05d}"


FALLA_ALLOWED_MIME = {
    "application/pdf", "image/jpeg", "image/png", "image/webp",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword", "text/csv",
}
FALLA_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
DRIVE_ROOT_FOLDER_ID = "1GlX0E_OKdyT2kkS9y6gtYyTuASnsrbHc"

def _get_drive_service():
    import json, os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise HTTPException(500, "Google Drive no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON)")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed=false")
    res = service.files().list(q=q, fields="files(id)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]

# ── SLA defaults ─────────────────────────────────────────────────────────────
# Default SLA hours by priority level (used when sla_limite_horas is not set)
_DEFAULT_SLA_HOURS = {
    1: 8,     # critica
    2: 24,    # alta
    3: 72,    # media
    4: 168,   # baja (7 days)
}

# Average energy price COP/kWh for economic impact estimation
_PRECIO_ENERGIA_COP_KWH = 800.0

# Solar capacity factor for kWh loss estimation
_SOLAR_CAPACITY_FACTOR = 0.18


def _estimar_perdida_falla(potencia_kwp, horas_fuera: float) -> tuple[float, float]:
    """Estima (kWh perdidos, impacto COP) de una falla. `solar_hours` aproxima las
    horas productivas como ~50% del downtime (≈12 h solares por 24 h). Función pura
    y testeable; alimenta el reporte SLA/económico, por eso conviene fijarla con tests.
    """
    solar_hours = min(horas_fuera, (horas_fuera / 24) * 12) if horas_fuera > 0 else 0
    kwh_perdidos = round(potencia_kwp * _SOLAR_CAPACITY_FACTOR * solar_hours, 3) if potencia_kwp else 0.0
    impacto_cop = round(kwh_perdidos * _PRECIO_ENERGIA_COP_KWH, 2)
    return kwh_perdidos, impacto_cop


@router.get("/sla-dashboard", response_model=FallaSLADashboard)
def sla_dashboard(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """SLA monitoring dashboard with risk, overdue, and compliance metrics."""
    now = datetime.now(timezone.utc)

    # Get all open fallas with their priority info
    open_fallas = (
        db.query(Falla, FallaCatPrioridad.nivel)
        .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
        .join(FallaCatPrioridad, Falla.prioridad_id == FallaCatPrioridad.id)
        .filter(Falla.deleted_at.is_(None), ~FallaCatEstado.es_estado_final)
        .all()
    )

    en_riesgo = 0
    vencido = 0
    for falla, nivel in open_fallas:
        sla_hours = falla.sla_limite_horas or _DEFAULT_SLA_HOURS.get(nivel, 72)
        sla_deadline = datetime(
            falla.fecha_identificacion.year,
            falla.fecha_identificacion.month,
            falla.fecha_identificacion.day,
            tzinfo=timezone.utc,
        ) + timedelta(hours=sla_hours)

        if now > sla_deadline:
            vencido += 1
        elif now > sla_deadline - timedelta(hours=sla_hours * 0.2):
            # Within last 20% of SLA window = at risk
            en_riesgo += 1

    # Average resolution time for resolved fallas in last 90 days
    resolved_fallas = (
        db.query(Falla)
        .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
        .filter(
            Falla.deleted_at.is_(None),
            FallaCatEstado.es_estado_final == True,
            Falla.fecha_resolucion.isnot(None),
            Falla.updated_at >= now - timedelta(days=90),
        )
        .all()
    )

    total_hours = 0.0
    count_resolved = 0
    sla_met = 0
    sla_evaluated = 0
    for f in resolved_fallas:
        if f.fecha_resolucion and f.fecha_identificacion:
            start = datetime(
                f.fecha_identificacion.year,
                f.fecha_identificacion.month,
                f.fecha_identificacion.day,
                tzinfo=timezone.utc,
            )
            hours = (f.fecha_resolucion - start).total_seconds() / 3600
            total_hours += hours
            count_resolved += 1

        if f.sla_cumplido is not None:
            sla_evaluated += 1
            if f.sla_cumplido:
                sla_met += 1

    promedio = round(total_hours / count_resolved, 1) if count_resolved else None
    cumplimiento = round(sla_met / sla_evaluated * 100, 1) if sla_evaluated else None

    return FallaSLADashboard(
        fallas_en_riesgo_sla=en_riesgo,
        fallas_sla_vencido=vencido,
        promedio_tiempo_resolucion_horas=promedio,
        cumplimiento_sla_pct=cumplimiento,
    )


@router.get("/catalogos", response_model=FallaCatalogos)
def get_catalogos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    estados = db.query(FallaCatEstado).order_by(FallaCatEstado.orden).all()
    prioridades = db.query(FallaCatPrioridad).order_by(FallaCatPrioridad.nivel).all()
    tipos = (
        db.query(FallaCatTipo)
        .options(selectinload(FallaCatTipo.categoria))
        .filter(FallaCatTipo.activa == True)
        .order_by(FallaCatTipo.etiqueta)
        .all()
    )
    resoluciones = db.query(FallaCatResolucion).order_by(FallaCatResolucion.etiqueta).all()
    return {"estados": estados, "prioridades": prioridades, "tipos": tipos, "resoluciones": resoluciones}



@router.get("/stats/resumen")
def stats_resumen(db: Session = Depends(get_db), _=Depends(get_current_user)):
    today = date.today()
    alert_cutoff = today - timedelta(days=7)

    def _count(*filters):
        q = db.query(func.count(Falla.id)).join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
        for f in filters:
            q = q.filter(f)
        return q.scalar() or 0

    total_activas = _count(~FallaCatEstado.es_estado_final)
    en_revision   = _count(FallaCatEstado.codigo == "en_gestion")
    resueltas_mes = _count(FallaCatEstado.es_estado_final == True, Falla.updated_at >= today.replace(day=1))
    sla_base = _count(FallaCatEstado.es_estado_final == True,
                      Falla.updated_at >= today - timedelta(days=30),
                      Falla.sla_cumplido.isnot(None))
    sla_ok   = _count(FallaCatEstado.es_estado_final == True,
                      Falla.updated_at >= today - timedelta(days=30),
                      Falla.sla_cumplido == True)
    alerta   = _count(~FallaCatEstado.es_estado_final, Falla.fecha_identificacion <= alert_cutoff)

    return {
        "total_activas": total_activas,
        "en_revision": en_revision,
        "resueltas_mes": resueltas_mes,
        "cumplimiento_sla_pct": round(sla_ok / sla_base * 100) if sla_base else None,
        "alerta_7_dias": alerta,
    }


@router.get("", response_model=PaginatedResponse[FallaOut])
def list_fallas(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=5000),
    page_size: int | None = Query(None, ge=1, le=5000),
    q: str | None = None,
    buscar: str | None = None,
    estado_id: int | None = None,
    estado_codigo: str | None = None,
    prioridad_id: int | None = None,
    prioridad_codigo: str | None = None,
    tipo_codigo: str | None = None,
    proyecto_id: int | None = None,
    cliente_id: int | None = None,
    asignado_a_id: int | None = None,
    codigo_legado: str | None = None,
    solo_alerta: bool = False,
    fecha_programada_desde: date | None = None,
    fecha_programada_hasta: date | None = None,
    con_fecha_programada: bool = False,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    effective_size = page_size or size
    search = q or buscar
    estado_joined = False

    query = db.query(Falla).filter(Falla.deleted_at.is_(None)).options(*_FALLA_LOAD)

    if search:
        query = query.filter(Falla.descripcion.ilike(f"%{search}%") | Falla.codigo_interno.ilike(f"%{search}%"))
    if estado_id:
        query = query.filter(Falla.estado_id == estado_id)
    if estado_codigo:
        query = query.join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
        estado_joined = True
        query = query.filter(FallaCatEstado.codigo == estado_codigo)
    if prioridad_id:
        query = query.filter(Falla.prioridad_id == prioridad_id)
    if prioridad_codigo:
        query = (query.join(FallaCatPrioridad, Falla.prioridad_id == FallaCatPrioridad.id)
                      .filter(FallaCatPrioridad.codigo == prioridad_codigo))
    if tipo_codigo:
        query = (query.join(FallaCatTipo, Falla.tipo_id == FallaCatTipo.id)
                      .filter(FallaCatTipo.codigo == tipo_codigo))
    if proyecto_id:
        query = query.filter(Falla.proyecto_id == proyecto_id)
    if cliente_id:
        # Filter fallas by projects belonging to a specific client
        client_project_ids = (
            db.query(Proyecto.id)
            .filter(Proyecto.cliente_id == cliente_id, Proyecto.deleted_at.is_(None))
            .subquery()
        )
        query = query.filter(Falla.proyecto_id.in_(client_project_ids))
    if asignado_a_id:
        query = query.filter(Falla.asignado_a_id == asignado_a_id)
    if codigo_legado:
        query = query.filter(Falla.codigo_legado == codigo_legado)
    if solo_alerta:
        alert_cutoff = date.today() - timedelta(days=7)
        if not estado_joined:
            query = query.join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
        query = query.filter(~FallaCatEstado.es_estado_final, Falla.fecha_identificacion <= alert_cutoff)
    if fecha_programada_desde:
        query = query.filter(Falla.fecha_programada >= fecha_programada_desde)
    if fecha_programada_hasta:
        query = query.filter(Falla.fecha_programada <= fecha_programada_hasta)
    if con_fecha_programada:
        query = query.filter(Falla.fecha_programada.isnot(None))

    total = query.count()
    items = query.order_by(Falla.created_at.desc()).offset((page - 1) * effective_size).limit(effective_size).all()
    return {"items": items, "total": total, "page": page, "size": effective_size, "pages": -(-total // effective_size)}


def _get_correos_cliente(proyecto_id: int, db) -> list[str]:
    """Retorna la lista de correos operacionales del cliente del proyecto."""
    from app.models.proyectos import Proyecto
    from app.models.clientes import Cliente
    proy = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proy or not proy.cliente_id:
        return []
    cliente = db.query(Cliente).filter(Cliente.id == proy.cliente_id).first()
    if not cliente:
        return []
    # Preferir array; fallback al campo string si el array está vacío
    arr = cliente.correos_operacionales or []
    if isinstance(arr, list) and arr:
        return [str(e) for e in arr if e]
    if cliente.correo_operacional:
        return [cliente.correo_operacional]
    return []


_notif_logger = logging.getLogger("fallas.notificacion")


def _enviar_notificacion(
    falla,
    accion: str,
    usuario_nombre: str,
    db,
) -> dict:
    """
    Envía email de notificación y retorna el resultado.
    Nunca lanza excepción — la falla se guarda siempre.
    Retorna: {"ok": bool, "enviados": [...], "errores": [...], "sin_correos": bool}
    """
    from app.services.email_service import send_falla_notification_email
    from app.core.config import settings
    from datetime import datetime, timezone

    correos = _get_correos_cliente(falla.proyecto_id, db)
    ts = datetime.now(timezone.utc).isoformat()

    if not correos:
        _notif_logger.warning(
            "[%s] usuario=%s falla=%s accion=%s — SIN correos operacionales para proyecto %s",
            ts, usuario_nombre, falla.codigo_interno, accion, falla.proyecto_id,
        )
        return {"ok": False, "enviados": [], "errores": ["Sin correos operacionales configurados para este cliente"], "sin_correos": True}

    resultado = send_falla_notification_email(
        to_emails=correos,
        codigo_falla=falla.codigo_interno,
        proyecto_nombre=falla.proyecto.nombre_comercial if falla.proyecto else str(falla.proyecto_id),
        descripcion=falla.descripcion or "",
        estado_codigo=falla.estado.codigo if falla.estado else "",
        estado_etiqueta=falla.estado.etiqueta if falla.estado else "",
        prioridad_etiqueta=falla.prioridad.etiqueta if falla.prioridad else "",
        fecha_identificacion=str(falla.fecha_identificacion or ""),
        hora_identificacion=str(falla.hora_identificacion or ""),
        asignado_a=falla.asignado_a.nombre if falla.asignado_a else None,
        registrado_por=usuario_nombre,
        accion=accion,
        frontend_url=settings.FRONTEND_URL,
    )
    resultado["sin_correos"] = False

    if resultado.get("ok"):
        _notif_logger.info(
            "[%s] usuario=%s falla=%s accion=%s — ENVIADO a: %s",
            ts, usuario_nombre, falla.codigo_interno, accion, resultado["enviados"],
        )
    else:
        _notif_logger.error(
            "[%s] usuario=%s falla=%s accion=%s — ERROR: %s",
            ts, usuario_nombre, falla.codigo_interno, accion, resultado["errores"],
        )

    return resultado


@router.post("", response_model=FallaOut, status_code=201)
def create_falla(
    data: FallaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    dump = data.model_dump()
    fotos = dump.pop("fotos_urls", None)
    falla = Falla(
        **dump,
        codigo_interno=_gen_codigo(db),
        registrado_por_id=current_user.id,
        fotos_urls=fotos if fotos else None,
    )
    db.add(falla)
    db.commit()
    return _get_or_404(falla.id, db)


@router.get("/{id}", response_model=FallaOut)
def get_falla(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_or_404(id, db)


@router.patch("/{id}", response_model=FallaOut)
def update_falla(
    id: int,
    data: FallaUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    dump = data.model_dump(exclude_unset=True)
    for k, v in dump.items():
        setattr(falla, k, v)
    db.commit()
    return _get_or_404(id, db)


@router.post("/{id}/notificar")
def notificar_falla(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Envía la notificación por correo para la falla indicada.
    Se llama desde el frontend tras guardar cuando notificacion=True.
    Retorna: {"ok", "enviados", "errores", "sin_correos"}
    """
    falla = _get_or_404(id, db)
    accion = "cerrada" if falla.estado and falla.estado.es_estado_final else "creada"
    return _enviar_notificacion(
        falla=falla,
        accion=accion,
        usuario_nombre=current_user.nombre,
        db=db,
    )


@router.delete("/{id}", status_code=204)
def delete_falla(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    falla.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/{id}/seguimientos", response_model=FallaSeguimientoOut, status_code=201)
def add_seguimiento(
    id: int,
    data: FallaSeguimientoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")

    seg = FallaSeguimiento(
        falla_id=id,
        usuario_id=current_user.id,
        nota=data.nota,
        estado_nuevo_id=data.estado_nuevo_id,
    )
    if data.estado_nuevo_id:
        falla.estado_id = data.estado_nuevo_id

    db.add(seg)
    db.commit()
    db.refresh(seg)

    return (
        db.query(FallaSeguimiento)
        .options(
            selectinload(FallaSeguimiento.usuario),
            selectinload(FallaSeguimiento.estado_nuevo),
        )
        .filter(FallaSeguimiento.id == seg.id)
        .first()
    )


# ── Feature 4: Impact on generation ─────────────────────────────────────────
@router.get("/{id}/impacto", response_model=FallaImpacto)
def get_falla_impacto(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """
    Estimate generation loss and economic impact for a falla based on
    project capacity and downtime duration.
    """
    falla = db.query(Falla).options(selectinload(Falla.proyecto)).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")

    proyecto = falla.proyecto
    potencia_kwp = float(proyecto.potencia_instalada_kwp or 0)

    # Calculate downtime hours
    start = datetime(
        falla.fecha_identificacion.year,
        falla.fecha_identificacion.month,
        falla.fecha_identificacion.day,
        tzinfo=timezone.utc,
    )
    if falla.hora_identificacion:
        start = start.replace(
            hour=falla.hora_identificacion.hour,
            minute=falla.hora_identificacion.minute,
        )

    end = falla.fecha_resolucion or datetime.now(timezone.utc)
    horas_fuera = max(0, (end - start).total_seconds() / 3600)

    kwh_perdidos, impacto_cop = _estimar_perdida_falla(potencia_kwp, horas_fuera)

    # Persist the estimate back to the falla if not already set
    if falla.kwh_perdidos_estimado is None:
        falla.kwh_perdidos_estimado = kwh_perdidos
        falla.impacto_economico_cop = impacto_cop
        db.commit()

    return FallaImpacto(
        falla_id=falla.id,
        proyecto_nombre=proyecto.nombre_comercial,
        potencia_instalada_kwp=potencia_kwp or None,
        horas_fuera=round(horas_fuera, 1),
        kwh_perdidos_estimado=kwh_perdidos,
        impacto_economico_cop=impacto_cop,
    )


# ── Feature 6: File attachments for fallas → Google Drive ────────────────────
@router.post("/{id}/archivos")
@router.post("/{id}/attachments")
async def upload_falla_attachment(
    id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    falla = db.query(Falla).options(selectinload(Falla.proyecto)).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")

    if archivo.content_type not in FALLA_ALLOWED_MIME:
        raise HTTPException(400, "Tipo de archivo no permitido.")

    contenido = await archivo.read()
    if len(contenido) > FALLA_MAX_FILE_SIZE:
        raise HTTPException(400, "El archivo supera el límite de 20 MB")

    import io
    from googleapiclient.http import MediaIoBaseUpload

    service = _get_drive_service()

    # Estructura: Raíz → Proyecto → Código falla
    proyecto_nombre = falla.proyecto.nombre_comercial if falla.proyecto else f"Proyecto {falla.proyecto_id}"
    proyecto_folder_id = _get_or_create_folder(service, proyecto_nombre, DRIVE_ROOT_FOLDER_ID)
    falla_folder_id    = _get_or_create_folder(service, falla.codigo_interno or f"FAL-{id}", proyecto_folder_id)

    nombre_original = archivo.filename or f"archivo_{uuid.uuid4().hex}"
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=archivo.content_type or "application/octet-stream")
    file_meta = {"name": nombre_original, "parents": [falla_folder_id]}
    uploaded = service.files().create(body=file_meta, media_body=media, fields="id, webViewLink").execute()

    file_id  = uploaded["id"]
    view_url = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
    # Encode filename in URL fragment so frontend can detect type and show name
    url = f"{view_url}#{nombre_original}"

    current_urls = falla.fotos_lista
    current_urls.append(url)
    falla.fotos_urls = current_urls
    db.commit()

    return {
        "status": "ok",
        "url": url,
        "file_id": file_id,
        "filename": nombre_original,
        "fotos_urls": current_urls,
    }
