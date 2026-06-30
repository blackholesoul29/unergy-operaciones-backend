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
    Falla, FallaSeguimiento, FallaIntervalo, FallaInversor,
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
from app.services.fallas.estructura import (
    ESTRUCTURA_FALLAS, get_categoria, validar_clasificacion, tipo_codigo,
    etiqueta_subtipo, es_subtipo_pendiente,
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
    selectinload(Falla.intervalos),
    selectinload(Falla.inversores_afectados),
    _SEGS_LOAD,
]


def _validar_clasificacion_payload(categoria_codigo, subtipo_codigo, inversores) -> None:
    """Valida el payload estructurado contra la estructura canónica; 422 si inválido."""
    inv_tipos = sorted({t for inv in (inversores or []) for t in (_inv_tipos(inv))})
    ok, err = validar_clasificacion(categoria_codigo, subtipo_codigo, inv_tipos)
    if not ok:
        raise HTTPException(422, f"Clasificación inválida: {err}")


def _inv_tipos(inv) -> list:
    """tipos de un inversor venga como dict (model_dump) o como objeto pydantic."""
    if isinstance(inv, dict):
        return inv.get("tipos") or []
    return getattr(inv, "tipos", None) or []


def _inv_get(inv, key):
    if isinstance(inv, dict):
        return inv.get(key)
    return getattr(inv, key, None)


def _sync_falla_inversores(falla: Falla, inversores: list | None, db: Session) -> None:
    """Reemplaza los inversores afectados de la falla (replace-all)."""
    if inversores is None:
        return
    db.query(FallaInversor).filter(FallaInversor.falla_id == falla.id).delete(synchronize_session=False)
    for inv in inversores:
        tipos = _inv_tipos(inv)
        db.add(FallaInversor(
            falla_id=falla.id,
            proyecto_inversor_id=_inv_get(inv, "proyecto_inversor_id"),
            nombre=_inv_get(inv, "nombre"),
            potencia_kw=_inv_get(inv, "potencia_kw"),
            tipos=tipos or [],
        ))


def _aplicar_clasificacion(falla: Falla, inversores: list | None, db: Session) -> None:
    """Deriva tipo_id/pendiente/flags/clasificacion a partir de las columnas ya
    asignadas en `falla` y la lista de inversores. Sincroniza falla_inversores.

    Asume que la clasificación ya fue validada. Para `inversores=None` (PATCH que no
    toca inversores) recalcula a partir de las filas existentes en BD.
    """
    categoria = falla.categoria_codigo
    cat = get_categoria(categoria) if categoria else None
    if not cat:
        return

    # Fuente de inversores para derivar: input nuevo o filas existentes.
    if inversores is None and categoria == "inversores":
        existentes = db.query(FallaInversor).filter(FallaInversor.falla_id == falla.id).all()
        inv_source = [
            {"proyecto_inversor_id": e.proyecto_inversor_id, "nombre": e.nombre,
             "potencia_kw": float(e.potencia_kw) if e.potencia_kw is not None else None,
             "tipos": e.tipos or []}
            for e in existentes
        ]
    else:
        inv_source = inversores or []

    inv_tipos_all = sorted({t for inv in inv_source for t in _inv_tipos(inv)})

    # pendiente_reclasificar deriva del subtipo (p.ej. desconexión sin identificar)
    falla.pendiente_reclasificar = es_subtipo_pendiente(categoria, falla.subtipo_codigo)
    # flag de comunicación de inversores (solo aplica a categoría inversores)
    falla.inversores_perdida_comunicacion = (
        ("perdida_comunicacion" in inv_tipos_all) if categoria == "inversores" else None
    )
    # frontera flags solo aplican a frontera
    if categoria != "frontera":
        falla.frontera_afecta_medicion = None
        falla.frontera_perdida_comunicacion = None

    # Mapeo a tipo de catálogo (para que vistas/analytics legacy muestren etiqueta)
    nuevo_tipo_id = None
    if categoria in ("red", "frontera", "eventos_adversos") and falla.subtipo_codigo:
        t = db.query(FallaCatTipo).filter_by(codigo=tipo_codigo(categoria, falla.subtipo_codigo)).first()
        if t:
            nuevo_tipo_id = t.id
    elif categoria == "inversores" and inv_tipos_all:
        t = db.query(FallaCatTipo).filter_by(codigo=tipo_codigo("inversores", inv_tipos_all[0])).first()
        if t:
            nuevo_tipo_id = t.id
    if nuevo_tipo_id:
        falla.tipo_id = nuevo_tipo_id

    # Snapshot estructurado (fuente para mostrar/auditar)
    clasif = {"categoria": categoria, "categoria_etiqueta": cat["etiqueta"]}
    if falla.subtipo_codigo:
        clasif["subtipo"] = falla.subtipo_codigo
        clasif["subtipo_etiqueta"] = etiqueta_subtipo(categoria, falla.subtipo_codigo)
    if falla.subtipo_detalle:
        clasif["detalle"] = falla.subtipo_detalle
    if categoria == "frontera":
        clasif["afecta_medicion"] = bool(falla.frontera_afecta_medicion)
        clasif["perdida_comunicacion"] = bool(falla.frontera_perdida_comunicacion)
    if categoria == "inversores":
        clasif["inversores"] = [
            {
                "proyecto_inversor_id": _inv_get(inv, "proyecto_inversor_id"),
                "nombre": _inv_get(inv, "nombre"),
                "potencia_kw": _inv_get(inv, "potencia_kw"),
                "tipos": _inv_tipos(inv),
                "tipos_etiquetas": [etiqueta_subtipo("inversores", t) or t for t in _inv_tipos(inv)],
            }
            for inv in inv_source
        ]
        # tipo_libre legible para las listas/tablas legacy
        nombres = ", ".join(
            [(_inv_get(inv, "nombre") or f"Inv {_inv_get(inv, 'proyecto_inversor_id')}") for inv in inv_source]
        ) or "Inversores"
        tlabels = ", ".join([etiqueta_subtipo("inversores", t) or t for t in inv_tipos_all])
        falla.tipo_libre = (f"Inversores: {nombres} — {tlabels}")[:255]
    falla.clasificacion = clasif

    # Reemplaza filas de inversores afectados solo si vino input nuevo.
    _sync_falla_inversores(falla, inversores, db)


def _alarmas_post_guardado(falla_id: int, db: Session) -> None:
    """Hook de alarmas de comunicación tras crear/actualizar. Nunca rompe el flujo."""
    try:
        from app.services.fallas.alarmas import evaluar_alarmas_falla
        falla = db.query(Falla).options(selectinload(Falla.proyecto)).filter(Falla.id == falla_id).first()
        if falla and falla.categoria_codigo:
            evaluar_alarmas_falla(db, falla)
            db.commit()
    except Exception:
        db.rollback()
        logging.getLogger("fallas").exception("evaluar_alarmas_falla falló (no bloqueante)")


def _sync_intervalos(falla: Falla, intervalos: list | None, db: Session) -> None:
    """Reemplaza los intervalos de disparo de una falla con la lista recibida.
    `intervalos` es una lista de dicts {inicio, fin, nota}. Si es None, no se
    toca nada (no se enviaron). Si es [], se eliminan todos."""
    if intervalos is None:
        return
    # Borrar los existentes y recrear (replace-all). La lista suele ser pequeña.
    db.query(FallaIntervalo).filter(FallaIntervalo.falla_id == falla.id).delete(synchronize_session=False)
    for iv in intervalos:
        if not iv.get("inicio"):
            continue
        db.add(FallaIntervalo(
            falla_id=falla.id,
            inicio=iv["inicio"],
            fin=iv.get("fin"),
            nota=(iv.get("nota") or None),
        ))


def _get_or_404(id: int, db: Session) -> Falla:
    falla = db.query(Falla).options(*_FALLA_LOAD).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    return falla


def _gen_codigo(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    max_id = db.query(func.max(Falla.id)).scalar() or 0
    return f"FAL-{year}-{max_id + 1:05d}"


FALLA_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
DRIVE_ROOT_FOLDER_ID = "0AD_e3wIWHByDUk9PVA"

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
    res = service.files().list(
        q=q, fields="files(id)",
        supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(
        body=meta, fields="id",
        supportsAllDrives=True
    ).execute()
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
            tzinfo=_COL_TZ,
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
                tzinfo=_COL_TZ,
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


@router.get("/estructura")
def get_estructura(_=Depends(get_current_user)):
    """Estructura canónica del reporte jerárquico (sistema → opciones/equipos/tipos).
    Fuente única que consumen el form web y la app móvil."""
    return {"categorias": ESTRUCTURA_FALLAS}



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


_COL_TZ = timezone(timedelta(hours=-5))


def _col_day_start_utc() -> datetime:
    """Inicio del día actual en hora de Colombia (UTC-5), expresado en UTC."""
    now_col = datetime.now(_COL_TZ)
    start_col = now_col.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_col.astimezone(timezone.utc)


@router.get("/actividad-hoy")
def actividad_hoy(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Fallas creadas hoy y fallas que cambiaron de estado hoy (hora Colombia).

    Respuesta:
      { fecha,
        creadas: [FallaOut],
        cambios_estado: [{ falla: FallaOut, estado_anterior, estado_nuevo, hora }] }
    El `estado_anterior` se deduce del seguimiento de cambio inmediatamente previo.
    """
    day_start = _col_day_start_utc()
    hoy_str = datetime.now(_COL_TZ).date().isoformat()

    creadas = (
        db.query(Falla)
        .filter(Falla.deleted_at.is_(None), Falla.created_at >= day_start)
        .options(*_FALLA_LOAD)
        .order_by(Falla.created_at.desc())
        .all()
    )

    segs_hoy = (
        db.query(FallaSeguimiento)
        .filter(
            FallaSeguimiento.estado_nuevo_id.isnot(None),
            FallaSeguimiento.created_at >= day_start,
        )
        .all()
    )
    falla_ids = {s.falla_id for s in segs_hoy}

    cambios: list[dict] = []
    if falla_ids:
        # Historial de cambios de estado de esas fallas (ordenado) para deducir el anterior.
        hist = (
            db.query(FallaSeguimiento)
            .filter(
                FallaSeguimiento.falla_id.in_(falla_ids),
                FallaSeguimiento.estado_nuevo_id.isnot(None),
            )
            .options(selectinload(FallaSeguimiento.estado_nuevo))
            .order_by(FallaSeguimiento.falla_id, FallaSeguimiento.created_at)
            .all()
        )
        por_falla: dict[int, list] = {}
        for s in hist:
            por_falla.setdefault(s.falla_id, []).append(s)

        fallas = (
            db.query(Falla)
            .filter(Falla.id.in_(falla_ids), Falla.deleted_at.is_(None))
            .options(*_FALLA_LOAD)
            .all()
        )
        fallas_map = {f.id: f for f in fallas}

        def _estado_dict(estado):
            if not estado:
                return None
            return {"etiqueta": estado.etiqueta, "color_hex": estado.color_hex}

        for fid, segs in por_falla.items():
            falla = fallas_map.get(fid)
            if not falla:
                continue
            today_positions = [i for i, s in enumerate(segs) if s.created_at >= day_start]
            if not today_positions:
                continue
            last_i = today_positions[-1]
            ultimo = segs[last_i]
            anterior = segs[last_i - 1] if last_i > 0 else None
            cambios.append({
                "falla": FallaOut.model_validate(falla),
                "estado_anterior": _estado_dict(anterior.estado_nuevo if anterior else None),
                "estado_nuevo": _estado_dict(ultimo.estado_nuevo),
                "hora": ultimo.created_at.isoformat(),
            })
        cambios.sort(key=lambda c: c["hora"], reverse=True)

    return {
        "fecha": hoy_str,
        "creadas": [FallaOut.model_validate(f) for f in creadas],
        "cambios_estado": cambios,
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
        tipo_nombre=falla.tipo.etiqueta if falla.tipo else (falla.tipo_libre or ""),
        fecha_identificacion=str(falla.fecha_identificacion or ""),
        hora_identificacion=str(falla.hora_identificacion or ""),
        fecha_programada=str(falla.fecha_programada or ""),
        asignado_a=falla.asignado_a.nombre if falla.asignado_a else None,
        registrado_por=usuario_nombre,
        accion=accion,
        frontend_url=settings.FRONTEND_URL,
        falla_id=falla.id,
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
    intervalos = dump.pop("intervalos", None)
    inversores = dump.pop("inversores", None)  # no es columna → se procesa aparte

    # Camino estructurado: validar antes de crear nada.
    categoria_codigo = dump.get("categoria_codigo")
    if categoria_codigo:
        _validar_clasificacion_payload(categoria_codigo, dump.get("subtipo_codigo"), inversores)

    falla = Falla(
        **dump,
        codigo_interno=f"TMP-{uuid.uuid4().hex[:12]}",
        registrado_por_id=current_user.id,
        fotos_urls=fotos if fotos else None,
    )
    db.add(falla)
    db.flush()  # asigna falla.id por autoincremento (evita colisiones de código)
    falla.codigo_interno = f"FAL-{datetime.now(timezone.utc).year}-{falla.id:05d}"
    _sync_intervalos(falla, intervalos, db)
    if categoria_codigo:
        _aplicar_clasificacion(falla, inversores or [], db)
    db.commit()

    # Notificar a todos los coordinadores
    from app.api.v1.notificaciones import crear_notificacion
    from app.models.usuarios import RolEnum
    coordinadores = db.query(Usuario).filter(
        Usuario.rol == RolEnum.coordinador,
        Usuario.activo == True,
    ).all()
    proyecto_nombre = falla.proyecto.nombre_comercial if falla.proyecto else f"Proyecto {falla.proyecto_id}"
    for coord in coordinadores:
        crear_notificacion(
            db=db,
            usuario_id=coord.id,
            tipo="accion",
            titulo="Nueva falla registrada",
            mensaje=f"{falla.codigo_interno} — {proyecto_nombre}: {(falla.descripcion or '')[:80]}",
            link="/m/coordinador",
        )
    if coordinadores:
        db.commit()

    # Alarmas de comunicación (frontera / inversores / total) — no bloqueante
    _alarmas_post_guardado(falla.id, db)

    return _get_or_404(falla.id, db)


@router.get("/{id}", response_model=FallaOut)
def get_falla(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _get_or_404(id, db)


@router.patch("/{id}", response_model=FallaOut)
def update_falla(
    id: int,
    data: FallaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    dump = data.model_dump(exclude_unset=True)

    # Los intervalos de disparo se sincronizan aparte (no son una columna).
    sync_ints = "intervalos" in dump
    intervalos = dump.pop("intervalos", None)
    # Inversores afectados tampoco son columna.
    inversores_touched = "inversores" in dump
    inversores = dump.pop("inversores", None)

    nuevo_asignado_id = dump.get("asignado_a_id")
    notificar_asignacion = (
        "asignado_a_id" in dump
        and nuevo_asignado_id is not None
        and nuevo_asignado_id != falla.asignado_a_id
    )

    for k, v in dump.items():
        setattr(falla, k, v)

    if sync_ints:
        _sync_intervalos(falla, intervalos or [], db)

    # Reclasificación / edición estructurada: si se tocó la categoría o los
    # inversores, revalidar y recalcular tipo_id/flags/clasificación.
    estructura_touched = (
        inversores_touched
        or any(k in dump for k in (
            "categoria_codigo", "subtipo_codigo", "subtipo_detalle",
            "frontera_afecta_medicion", "frontera_perdida_comunicacion",
        ))
    )
    if estructura_touched and falla.categoria_codigo:
        db.flush()  # asegura falla.id para sincronizar inversores
        # Validar: para inversores solo si llegó lista nueva (si no, los datos
        # existentes ya eran válidos). Para red/frontera/eventos validar subtipo.
        if falla.categoria_codigo == "inversores":
            if inversores_touched:
                _validar_clasificacion_payload(falla.categoria_codigo, falla.subtipo_codigo, inversores)
        else:
            _validar_clasificacion_payload(falla.categoria_codigo, falla.subtipo_codigo, None)
        _aplicar_clasificacion(falla, inversores if inversores_touched else None, db)

    # Sellar fecha+hora de solución automáticamente al cerrar la falla (estado
    # final) si el usuario no la indicó explícitamente; al reabrir se limpia.
    # Replica el comportamiento de los seguimientos y del botón "Marcar resuelta".
    if "estado_id" in dump and dump["estado_id"] is not None:
        nuevo_estado = db.get(FallaCatEstado, dump["estado_id"])
        if nuevo_estado and nuevo_estado.es_estado_final:
            if not falla.fecha_resolucion:
                falla.fecha_resolucion = datetime.now(timezone.utc)
        elif nuevo_estado and not nuevo_estado.es_estado_final and "fecha_resolucion" not in dump:
            falla.fecha_resolucion = None

    db.commit()

    if notificar_asignacion:
        from app.api.v1.notificaciones import crear_notificacion
        proyecto_nombre = falla.proyecto.nombre_comercial if falla.proyecto else f"Proyecto {falla.proyecto_id}"
        crear_notificacion(
            db=db,
            usuario_id=nuevo_asignado_id,
            tipo="accion",
            titulo="Falla asignada a ti",
            mensaje=f"{falla.codigo_interno} — {proyecto_nombre}: {(falla.descripcion or '')[:80]}",
            link="/m/tecnico",
        )
        db.commit()

    # Reevaluar alarmas de comunicación tras el cambio — no bloqueante
    _alarmas_post_guardado(id, db)

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
        # Mantener fecha_resolucion en sincronía con el estado, igual que el
        # botón "Marcar resuelta": al pasar a estado final se sella la fecha;
        # al reabrir (estado no final) se limpia.
        nuevo_estado = db.get(FallaCatEstado, data.estado_nuevo_id)
        if nuevo_estado and nuevo_estado.es_estado_final:
            if not falla.fecha_resolucion:
                falla.fecha_resolucion = datetime.now(timezone.utc)
        elif nuevo_estado and not nuevo_estado.es_estado_final:
            falla.fecha_resolucion = None

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
        tzinfo=_COL_TZ,
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

def _fotos_as_objects(raw_list: list) -> list[dict]:
    """Normaliza la lista almacenada en fotos_urls a objetos con campos completos.
    Soporta tanto el formato legado (strings de URL) como el nuevo (dicts)."""
    result = []
    for item in raw_list:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, str):
            # Formato legado: "url#nombre"
            if "#" in item:
                url_part, nombre_part = item.rsplit("#", 1)
            else:
                url_part, nombre_part = item, item.split("/")[-1]
            result.append({
                "id": url_part.split("/d/")[-1].split("/")[0] if "/d/" in url_part else uuid.uuid4().hex,
                "nombre": nombre_part,
                "url": url_part,
                "tamaño": None,
                "tipo_mime": None,
                "created_at": None,
            })
    return result


@router.get("/{id}/archivos")
def get_falla_archivos(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")
    return _fotos_as_objects(falla.fotos_lista)


@router.delete("/{id}/archivos/{archivo_id}")
def delete_falla_archivo(
    id: int,
    archivo_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    falla = db.query(Falla).filter(Falla.id == id).first()
    if not falla:
        raise HTTPException(404, "Falla no encontrada")

    items = _fotos_as_objects(falla.fotos_lista)
    nueva_lista = [i for i in items if i.get("id") != archivo_id]
    if len(nueva_lista) == len(items):
        raise HTTPException(404, "Archivo no encontrado")

    # Intentar eliminar de Drive (no crítico si falla)
    try:
        service = _get_drive_service()
        service.files().delete(fileId=archivo_id, supportsAllDrives=True).execute()
    except Exception:
        pass

    falla.fotos_urls = nueva_lista if nueva_lista else None
    db.commit()
    return {"status": "ok"}


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

    contenido = await archivo.read()
    tamaño = len(contenido)
    if tamaño > FALLA_MAX_FILE_SIZE:
        raise HTTPException(400, "El archivo supera el límite de 20 MB")

    import io
    from googleapiclient.http import MediaIoBaseUpload

    try:
        service = _get_drive_service()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error iniciando Drive: {e}")

    # Estructura: Raíz → Proyecto → Código falla
    proyecto_nombre = falla.proyecto.nombre_comercial if falla.proyecto else f"Proyecto {falla.proyecto_id}"
    try:
        proyecto_folder_id = _get_or_create_folder(service, proyecto_nombre, DRIVE_ROOT_FOLDER_ID)
        falla_folder_id    = _get_or_create_folder(service, falla.codigo_interno or f"FAL-{id}", proyecto_folder_id)
    except Exception as e:
        raise HTTPException(500, f"Error accediendo carpeta Drive: {e}")

    nombre_original = archivo.filename or f"archivo_{uuid.uuid4().hex}"
    tipo_mime = archivo.content_type or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=tipo_mime)
    file_meta = {"name": nombre_original, "parents": [falla_folder_id]}
    try:
        uploaded = service.files().create(
            body=file_meta, media_body=media, fields="id, webViewLink",
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        raise HTTPException(500, f"Error subiendo archivo a Drive: {e}")

    file_id  = uploaded["id"]
    view_url = uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    nuevo_archivo = {
        "id": file_id,
        "nombre": nombre_original,
        "url": view_url,
        "tamaño": tamaño,
        "tipo_mime": tipo_mime,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Normalizar lista existente (por si hay strings legados) y agregar nuevo
    items = _fotos_as_objects(falla.fotos_lista)
    items.append(nuevo_archivo)
    falla.fotos_urls = items
    db.commit()

    return nuevo_archivo
