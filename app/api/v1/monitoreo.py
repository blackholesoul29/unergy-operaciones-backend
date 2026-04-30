"""
Adapter endpoints for the monitoreo UI.
Translates between the vanilla-JS fallas-unergy format and the PostgreSQL models.

State mapping:
  monitoreo UI  <->  FallaCatEstado.codigo
  activa        <->  abierta
  revision      <->  en_gestion
  programada    <->  en_espera
  terminada     <->  cerrada / sin_solucion
"""
import calendar
import json
import random
import string
from datetime import datetime, date, timedelta, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import (
    Falla, FallaSeguimiento,
    FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria, FallaCatResolucion,
    GeneracionDiaria, MonitoreoVerificacion, GestionRegistro,
)
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto, Portafolio
from app.models.contratos import ContratoServicio
from app.models.mantenimientos import Mantenimiento
from app.utils.proyecto_matching import find_proyecto_by_name

router = APIRouter(prefix="/monitoreo", tags=["Monitoreo"])

# ── JSON catalog lookup (loaded once at import) ───────────────────────────────
_JSON_LABEL: dict[str, str] = {}

def _load_json_labels() -> None:
    from pathlib import Path as _P
    import json as _j
    p = _P("data/fallas_clasificadas_unergy.json")
    if not p.exists():
        return
    try:
        for entry in _j.loads(p.read_text(encoding="utf-8")):
            code = entry.get("Código de Falla", "").strip()
            evento = entry.get("Evento", "").strip()
            if code and evento:
                _JSON_LABEL[code] = evento
    except Exception:
        pass

_load_json_labels()

_OLD_CAT_NUM = {
    "inversor": "2", "comunicacion": "1", "produccion": "4",
    "red": "2", "estructura": "5", "medicion": "1", "otro": "p",
}

# ── Estado mappings ────────────────────────────────────────────────────────────

_CODIGO_A_ST = {
    "abierta": "activa",
    "en_gestion": "revision",
    "en_espera": "programada",
    "cerrada": "terminada",
    "sin_solucion": "terminada",
}
_ST_A_CODIGO = {
    "activa": "abierta",
    "revision": "en_gestion",
    "programada": "en_espera",
    "terminada": "cerrada",
}

# ── Eager loading ─────────────────────────────────────────────────────────────

_FALLA_EAGER = [
    selectinload(Falla.proyecto),
    selectinload(Falla.tipo).selectinload(FallaCatTipo.categoria),
    selectinload(Falla.estado),
    selectinload(Falla.prioridad),
    selectinload(Falla.resolucion),
    selectinload(Falla.registrado_por),
    selectinload(Falla.asignado_a),
    selectinload(Falla.seguimientos).selectinload(FallaSeguimiento.usuario),
    selectinload(Falla.seguimientos).selectinload(FallaSeguimiento.estado_nuevo),
]


# ── Helper ────────────────────────────────────────────────────────────────────

def _falla_to_fault(f: Falla) -> dict:
    st = _CODIGO_A_ST.get(f.estado.codigo if f.estado else "abierta", "activa")

    seguimiento_txt = ""
    segs = f.seguimientos if isinstance(f.seguimientos, list) else []
    if segs:
        lineas = []
        for seg in sorted(segs, key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc)):
            ts = seg.created_at.strftime("%d/%m/%Y %H:%M") if seg.created_at else ""
            quien = seg.usuario.nombre if seg.usuario else "—"
            lineas.append(f"{ts} - {quien}: {seg.nota or ''}")
        seguimiento_txt = "\n".join(lineas)

    fotos_lista: list[str] = f.fotos_lista  # property handles JSON parsing + empty fallback

    tipo_code = f.tipo.codigo if f.tipo else ""
    tipo_etiqueta = f.tipo.etiqueta if f.tipo else ""
    # Prefer JSON catalog label; fallback to DB etiqueta; last resort humanize the code
    fault_label = _JSON_LABEL.get(tipo_code) or tipo_etiqueta or ""
    if fault_label and " " not in fault_label and "_" in fault_label:
        fault_label = fault_label.replace("_", " ").title()

    cat_codigo = f.tipo.categoria.codigo if f.tipo and f.tipo.categoria else ""
    cat_num = cat_codigo if cat_codigo.isdigit() else _OLD_CAT_NUM.get(cat_codigo, "")

    drive_url = fotos_lista[0] if fotos_lista else ""

    return {
        "id": f.codigo_interno,
        "proj": f.proyecto.nombre_comercial if f.proyecto else "",
        "code": tipo_code,
        "faultLabel": fault_label,
        "catNum": cat_num,
        "st": st,
        "date": f.fecha_identificacion.isoformat() if f.fecha_identificacion else "",
        "time": f.hora_identificacion.strftime("%H:%M") if f.hora_identificacion else "",
        "occ": f.fecha_ocurrencia.strftime("%d/%m/%Y %H:%M") if f.fecha_ocurrencia else "",
        "res": f.resolucion.etiqueta if f.resolucion else "",
        "desc": f.descripcion or "",
        "flw": seguimiento_txt,
        "driveUrl": drive_url,
        "driveUrls": fotos_lista,
        "driUe": drive_url,
        "driUes": fotos_lista,
        "endDT": f.fecha_resolucion.strftime("%d/%m/%Y %H:%M") if f.fecha_resolucion else "",
        "centinela": f.centinela or "",
        "prio": f.prioridad.codigo if f.prioridad else "media",
        "notify": bool(f.notificacion),
        "photos": [],
        "_db_id": f.id,
        "_dias_abierta": f.dias_abierta,
        "_categoria_id": cat_codigo,
        "_categoria_lbl": f.tipo.categoria.etiqueta if f.tipo and f.tipo.categoria else "",
    }


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s.split(" ")[0], fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── Fallas endpoints ──────────────────────────────────────────────────────────

@router.get("/fallas")
def get_fallas_monitoreo(
    proyecto_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Falla).options(*_FALLA_EAGER)
    if proyecto_id:
        q = q.filter(Falla.proyecto_id == proyecto_id)
    fallas = q.order_by(Falla.created_at.desc()).all()
    return {"ok": True, "faults": [_falla_to_fault(f) for f in fallas]}


@router.post("/fallas/save")
def save_falla_monitoreo(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    fault_id: str = (payload.get("id") or "").strip()
    is_new = not fault_id

    nombre_proyecto = (payload.get("project") or "").strip()
    proyecto: Proyecto | None = None
    if nombre_proyecto:
        proyecto = find_proyecto_by_name(db, nombre_proyecto)
    if not proyecto:
        raise HTTPException(400, f"No se encontró proyecto para '{nombre_proyecto}'")

    st_code = _ST_A_CODIGO.get(payload.get("status", "activa"), "abierta")
    estado = db.query(FallaCatEstado).filter(FallaCatEstado.codigo == st_code).first()
    if not estado:
        raise HTTPException(400, f"Estado no reconocido: {st_code}")

    fault_code = (payload.get("faultCode") or "").strip()
    tipo = db.query(FallaCatTipo).filter(FallaCatTipo.codigo == fault_code).first()
    if not tipo:
        cat_id_str = str(payload.get("categoryId", "")).strip()
        cat = (
            db.query(FallaCatCategoria).filter(FallaCatCategoria.codigo == cat_id_str).first()
            if cat_id_str else None
        )
        tipo = (
            db.query(FallaCatTipo)
            .filter(FallaCatTipo.categoria_id == cat.id, FallaCatTipo.activa == True)
            .first()
            if cat else None
        )
        if not tipo:
            raise HTTPException(400, f"Tipo de falla no reconocido: {fault_code}")

    prio_codigo = (payload.get("prioridad") or "media").lower()
    prioridad = db.query(FallaCatPrioridad).filter(FallaCatPrioridad.codigo == prio_codigo).first()
    if not prioridad:
        prioridad = db.query(FallaCatPrioridad).order_by(FallaCatPrioridad.nivel).first()

    resolucion = None
    res_texto = (payload.get("resType") or "").strip()
    if res_texto:
        resolucion = (
            db.query(FallaCatResolucion)
            .filter(FallaCatResolucion.etiqueta.ilike(f"%{res_texto}%"))
            .first()
        )

    fecha_id = _parse_date(payload.get("identDate", "")) or date.today()
    fecha_ocurrencia = _parse_datetime(payload.get("occTime", ""))
    fecha_resolucion = _parse_datetime(payload.get("endTime", ""))

    fotos_urls_payload: list[str] = payload.get("driUes") or []
    drive_url = (payload.get("driUe") or "").strip()
    if drive_url and drive_url not in fotos_urls_payload:
        fotos_urls_payload = [drive_url] + fotos_urls_payload
    fotos_json = json.dumps(fotos_urls_payload) if fotos_urls_payload else None

    centinela = (payload.get("centinela") or current_user.nombre or "").strip()
    followup_nuevo = (payload.get("follwUp") or "").strip()

    if is_new:
        from sqlalchemy import func as sqlfunc
        year = datetime.now(timezone.utc).year
        count = db.query(sqlfunc.count(Falla.id)).scalar() or 0
        codigo = f"FAL-{year}-{count + 1:05d}"

        falla = Falla(
            codigo_interno=codigo,
            proyecto_id=proyecto.id,
            tipo_id=tipo.id,
            estado_id=estado.id,
            prioridad_id=prioridad.id,
            resolucion_id=resolucion.id if resolucion else None,
            registrado_por_id=current_user.id,
            descripcion=payload.get("desc") or payload.get("faultLabel") or "Sin descripción",
            fecha_identificacion=fecha_id,
            fecha_ocurrencia=fecha_ocurrencia,
            fecha_resolucion=fecha_resolucion,
            fotos_urls=fotos_json,
            centinela=centinela,
            notificacion=bool(payload.get("notify", False)),
        )
        db.add(falla)
        db.flush()

        if followup_nuevo:
            db.add(FallaSeguimiento(
                falla_id=falla.id,
                usuario_id=current_user.id,
                nota=followup_nuevo,
            ))
        codigo_interno_out = falla.codigo_interno
    else:
        falla = (
            db.query(Falla)
            .options(*_FALLA_EAGER)
            .filter(Falla.codigo_interno == fault_id)
            .first()
        )
        if not falla:
            raise HTTPException(404, f"Falla {fault_id} no encontrada")

        falla.proyecto_id = proyecto.id
        falla.tipo_id = tipo.id
        falla.estado_id = estado.id
        falla.prioridad_id = prioridad.id
        falla.resolucion_id = resolucion.id if resolucion else None
        falla.descripcion = payload.get("desc") or payload.get("faultLabel") or falla.descripcion
        falla.fecha_identificacion = fecha_id
        falla.fecha_ocurrencia = fecha_ocurrencia
        falla.fecha_resolucion = fecha_resolucion
        falla.fotos_urls = fotos_json
        falla.centinela = centinela
        falla.notificacion = bool(payload.get("notify", False))

        if followup_nuevo:
            segs_list = falla.seguimientos if isinstance(falla.seguimientos, list) else []
            segs_sorted = sorted(segs_list, key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc))
            if not segs_sorted or segs_sorted[-1].nota != followup_nuevo:
                db.add(FallaSeguimiento(
                    falla_id=falla.id,
                    usuario_id=current_user.id,
                    nota=followup_nuevo,
                    estado_nuevo_id=estado.id,
                ))
        codigo_interno_out = fault_id

    db.commit()
    falla_out = (
        db.query(Falla)
        .options(*_FALLA_EAGER)
        .filter(Falla.codigo_interno == codigo_interno_out)
        .first()
    )
    return {"ok": True, "fault": _falla_to_fault(falla_out)}


@router.post("/fallas/delete")
def delete_falla_monitoreo(
    payload: dict,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    fault_id = (payload.get("id") or "").strip()
    if not fault_id:
        raise HTTPException(400, "Se requiere id")
    falla = db.query(Falla).filter(Falla.codigo_interno == fault_id).first()
    if not falla:
        raise HTTPException(404, f"Falla {fault_id} no encontrada")
    db.delete(falla)
    db.commit()
    return {"ok": True}


# ── Catálogo ──────────────────────────────────────────────────────────────────

@router.get("/catalogo")
def get_catalogo(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    categorias = (
        db.query(FallaCatCategoria)
        .options(selectinload(FallaCatCategoria.tipos))
        .filter(FallaCatCategoria.activa == True)
        .order_by(FallaCatCategoria.orden)
        .all()
    )
    return [
        {
            "id": cat.codigo,
            "lbl": cat.etiqueta,
            "ico": cat.icono or "🔧",
            "col": cat.color_hex or "#915BD8",
            "faults": [
                {"code": t.codigo, "label": t.etiqueta, "desc": t.descripcion or ""}
                for t in sorted([t for t in cat.tipos if t.activa], key=lambda t: t.codigo)
            ],
        }
        for cat in categorias
    ]


# ── Proyectos ─────────────────────────────────────────────────────────────────

@router.get("/proyectos")
def get_proyectos_monitoreo(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Proyectos en operación (srv_operacion o estado=en_operacion), con cliente."""
    from sqlalchemy import or_ as _or2
    proyectos = (
        db.query(Proyecto)
        .filter(
            _or2(Proyecto.srv_operacion == True, Proyecto.estado == "en_operacion")  # noqa: E712
        )
        .options(selectinload(Proyecto.cliente))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return {
        "proyectos": [p.nombre_comercial for p in proyectos],
        "proyectos_detalle": [
            {
                "id": p.id,
                "nombre": p.nombre_comercial,
                "alias": p.alias_monitoreo or "",
                "cliente_id": p.cliente_id,
                "cliente_nombre": p.cliente.razon_social_nombre if p.cliente else "",
            }
            for p in proyectos
        ],
    }


# ── Generación ────────────────────────────────────────────────────────────────

@router.get("/generacion")
def get_generacion_monitoreo(
    proyecto_nombre: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    pid = proyecto_id
    if not pid and proyecto_nombre:
        proy = find_proyecto_by_name(db, proyecto_nombre)
        if proy:
            pid = proy.id

    q = db.query(GeneracionDiaria)
    if pid:
        q = q.filter(GeneracionDiaria.proyecto_id == pid)
    if fecha_inicio:
        q = q.filter(GeneracionDiaria.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.filter(GeneracionDiaria.fecha <= fecha_fin)

    rows = q.order_by(GeneracionDiaria.fecha).all()
    return {
        "ok": True,
        "datos": [
            {
                "fecha": r.fecha.isoformat(),
                "kwh_real": float(r.kwh_real) if r.kwh_real is not None else None,
                "kwh_p90": float(r.kwh_p90) if r.kwh_p90 is not None else None,
                "kwh_autoconsumo": float(r.kwh_autoconsumo) if r.kwh_autoconsumo is not None else None,
            }
            for r in rows
        ],
    }


# ── Auth (OTP para UI pública) ────────────────────────────────────────────────

@router.post("/auth/verify-email")
def verify_email_monitoreo(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email requerido")
    user = db.query(Usuario).filter(Usuario.email == email, Usuario.activo == True).first()
    if not user:
        return {"ok": False, "msg": "Correo no registrado en la plataforma"}
    return {"ok": True, "nombre": user.nombre, "email": user.email, "rol": user.rol.value}


@router.post("/auth/send-code")
def send_code(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email requerido")

    codigo = "".join(random.choices(string.digits, k=6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    db.query(MonitoreoVerificacion).filter(
        MonitoreoVerificacion.email == email,
        MonitoreoVerificacion.usado == False,
    ).delete()

    db.add(MonitoreoVerificacion(email=email, codigo=codigo, expires_at=expires_at))
    db.commit()

    print(f"[MONITOREO] Código para {email}: {codigo}")
    return {"ok": True}


@router.post("/auth/verify-code")
def verify_code(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    codigo = (payload.get("code") or "").strip()
    if not email or not codigo:
        raise HTTPException(400, "Email y código requeridos")

    now = datetime.now(timezone.utc)
    verif = (
        db.query(MonitoreoVerificacion)
        .filter(
            MonitoreoVerificacion.email == email,
            MonitoreoVerificacion.codigo == codigo,
            MonitoreoVerificacion.usado == False,
            MonitoreoVerificacion.expires_at > now,
        )
        .first()
    )
    if not verif:
        return {"ok": False}

    verif.usado = True
    db.commit()

    proyectos = (
        db.query(Proyecto)
        .join(Proyecto.cliente)
        .filter(Proyecto.estado == "en_operacion")
        .all()
    )
    proyectos_cliente = [
        p.nombre_comercial for p in proyectos
        if p.cliente and any(
            getattr(p.cliente, f, None) and getattr(p.cliente, f, "").lower() == email
            for f in ("correo_electronico", "correo_monitoreo")
        )
    ]
    return {"ok": True, "projects": proyectos_cliente, "email": email}


# ── Legacy bridge — replaces Google Apps Script ───────────────────────────────

# Colombia is UTC-5 (no DST)
_COL_TZ = timezone(timedelta(hours=-5))

# ── Unergy API ────────────────────────────────────────────────────────────────

async def _unergy_token() -> str:
    auth_url = f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(auth_url, json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD})
        r.raise_for_status()
        data = r.json()
        return data.get("token") or data.get("access") or data.get("key") or ""


async def _fetch_unergy_raw(token: str, sub_project: str, from_iso: str, to_iso: str, verified_only: bool) -> list:
    params: dict = {
        "time_stamp__gte": from_iso,
        "time_stamp__lte": to_iso,
        "sub_project": sub_project,
        "limit": "10000",
    }
    if verified_only:
        params["verified_by_operator"] = "True"
    data_url = f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(data_url, params=params, headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 401:
            return []
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("results", [])


def _compute_deltas(readings: list, d_from_dt: datetime, d_to_dt: datetime) -> list:
    readings.sort(key=lambda x: x.get("time_stamp") or x.get("timestamp") or "")
    # Separate: prior readings (for baseline) and period readings
    before, period = [], []
    for r in readings:
        ts_raw = r.get("time_stamp") or r.get("timestamp") or ""
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if "T" in ts_raw else datetime.strptime(ts_raw[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_COL_TZ)
        except Exception:
            continue
        if ts < d_from_dt:
            before.append((ts, r))
        elif ts <= d_to_dt:
            period.append((ts, r))

    if not period:
        return []

    working = ([before[-1]] if before else []) + period
    result = []
    for i in range(1, len(working)):
        ts_prev, r_prev = working[i - 1]
        ts_curr, r_curr = working[i]
        gen_curr = float(r_curr.get("generacion") or r_curr.get("generation") or 0)
        gen_prev = float(r_prev.get("generacion") or r_prev.get("generation") or 0)
        delta = max(0.0, gen_curr - gen_prev)
        # Format in Colombia local time
        ts_local = ts_curr.astimezone(_COL_TZ)
        result.append({
            "time": ts_local.strftime("%Y-%m-%d %H:%M"),
            "date": ts_local.strftime("%Y-%m-%d"),
            "kwh": round(delta, 3),
        })
    return result


async def _action_get_generation(sub_project: str | None, date_from: str | None, date_to: str | None, db: Session) -> dict:
    if not sub_project:
        return {"ok": False, "error": "sub_project requerido"}

    try:
        d_from_date = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else date.today().replace(day=1)
        d_to_date = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else date.today()
    except Exception:
        return {"ok": False, "error": "Formato de fecha inválido (YYYY-MM-DD)"}

    # Colombia-aware datetimes (matches Apps Script behavior)
    d_from_dt = datetime(d_from_date.year, d_from_date.month, d_from_date.day, 0, 0, 0, tzinfo=_COL_TZ)
    d_to_dt = datetime(d_to_date.year, d_to_date.month, d_to_date.day, 23, 59, 59, tzinfo=_COL_TZ)
    # Extend start by 2 days to capture prior cumulative baseline
    fetch_from_dt = d_from_dt - timedelta(days=2)
    from_iso = fetch_from_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = d_to_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        token = await _unergy_token()
        readings = await _fetch_unergy_raw(token, sub_project, from_iso, to_iso, verified_only=True)
        if not readings:
            readings = await _fetch_unergy_raw(token, sub_project, from_iso, to_iso, verified_only=False)
    except Exception as e:
        return {"ok": False, "error": f"Error API Unergy: {e}"}

    filtered = _compute_deltas(readings, d_from_dt, d_to_dt)

    # P50/P90 simulation from project record
    simulation = None
    from sqlalchemy import or_
    proyecto = db.query(Proyecto).filter(
        or_(Proyecto.sub_project == sub_project, Proyecto.alias_monitoreo == sub_project)
    ).first()
    if proyecto and (proyecto.p90_mensual_kwh or proyecto.p50_mensual_kwh):
        try:
            month = d_from_date.month
            p90_list = json.loads(proyecto.p90_mensual_kwh) if proyecto.p90_mensual_kwh else [None] * 12
            p50_list = json.loads(proyecto.p50_mensual_kwh) if proyecto.p50_mensual_kwh else [None] * 12
            p90m = p90_list[month - 1] if len(p90_list) >= month else None
            p50m = p50_list[month - 1] if len(p50_list) >= month else None
            days_in_month = calendar.monthrange(d_from_date.year, month)[1]
            simulation = {
                "p90_monthly": p90m,
                "p50_monthly": p50m,
                "p90_daily": round(p90m / days_in_month, 1) if p90m else None,
            }
        except Exception:
            pass

    return {"ok": True, "data": filtered, "simulation": simulation}


def _action_get_projects(db: Session) -> dict:
    from sqlalchemy import or_
    proyectos = (
        db.query(Proyecto)
        .filter(
            or_(Proyecto.sub_project.isnot(None), Proyecto.alias_monitoreo.isnot(None)),
            Proyecto.estado == "en_operacion",
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return {
        "ok": True,
        "projects": [
            {
                "sub_project": p.sub_project or p.alias_monitoreo,
                "nombre_comercial": p.nombre_comercial,
                "nombre_clientes": p.nombre_clientes or p.nombre_comercial,
                "nombre_bitacora": p.nombre_bitacora or "",
                "nombre_display": p.nombre_clientes or p.nombre_bitacora or p.nombre_comercial,
                "municipio": p.municipio or "—",
                "departamento": p.departamento or "—",
                "potencia_instalada_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
                "estado": p.estado,
                "project_id_solenium": p.project_id_solenium or "",
            }
            for p in proyectos
        ],
    }


def _action_get_portfolios(db: Session) -> dict:
    """Clientes que tienen al menos un proyecto en operación (srv_operacion o en_operacion)."""
    from app.models.clientes import Cliente
    from sqlalchemy import or_
    clientes = (
        db.query(Cliente)
        .options(selectinload(Cliente.proyectos))
        .order_by(Cliente.razon_social_nombre)
        .all()
    )
    portfolios: dict = {}
    for c in clientes:
        projs = [
            {
                "nombre": p.nombre_clientes or p.nombre_comercial,
                "sub_project": p.sub_project or p.alias_monitoreo or "",
                "nombre_display": p.nombre_clientes or p.nombre_bitacora or p.nombre_comercial,
                "nombre_bitacora": p.nombre_bitacora or "",
                "nombre_comercial": p.nombre_comercial or "",
            }
            for p in c.proyectos
            if p.estado == "en_operacion" or p.srv_operacion
        ]
        if projs:
            portfolios[c.razon_social_nombre] = projs
    return {"ok": True, "portfolios": portfolios}


def _action_get_all_contratos(db: Session) -> dict:
    rows = (
        db.query(ContratoServicio)
        .filter(
            ContratoServicio.servicio_aplica == "operacion",
            ContratoServicio.estado.in_(["vigente", "en_renovacion"]),
        )
        .options(selectinload(ContratoServicio.proyecto))
        .all()
    )
    contratos = []
    for c in rows:
        p = c.proyecto
        slug = (p.sub_project or p.alias_monitoreo) if p else None
        if not slug:
            continue
        contratos.append({
            "sub_project": slug,
            "nombre_clientes": p.nombre_clientes or p.nombre_comercial,
            "disponibilidad_garantizada_pct": "97",
            "contratista": c.prestador_nombre or "Unergy S.A.S.",
            "valor_estimado_ano1_cop": str(round(float(c.tarifa_base) * 12)) if c.tarifa_base else "0",
            "garantias_equipos": "",
            "numero_contrato": c.numero_contrato or "",
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else "",
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else "",
            "project_id_solenium": p.project_id_solenium or "",
        })
    return {"ok": True, "contratos": contratos}


# ── Solenium token cache (module-level, resets on dyno restart) ───────────────
_sol_cache: dict = {"token": None, "expires_at": 0.0}


async def _solenium_token() -> str | None:
    import time
    if _sol_cache["token"] and time.time() < _sol_cache["expires_at"]:
        return _sol_cache["token"]
    if not settings.SOLENIUM_USER or not settings.SOLENIUM_PASS:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                settings.SOLENIUM_AUTH_URL,
                json={"username": settings.SOLENIUM_USER, "password": settings.SOLENIUM_PASS},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            token = data.get("access") or data.get("token") or data.get("key") or ""
            if token:
                import time as _t
                _sol_cache["token"] = token
                _sol_cache["expires_at"] = _t.time() + 20 * 3600
            return token or None
    except Exception:
        return None


async def _solenium_inverters(proyecto: Proyecto) -> tuple[list, str | None]:
    token = await _solenium_token()
    if not token:
        return [], "Solenium no configurado o sin credenciales"

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            # Step 1: get Solenium project list to find the ID
            r = await c.get(
                f"{settings.SOLENIUM_DATA_URL}/project/",
                params={"menu": "1"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 401:
                _sol_cache["token"] = None
                return [], "Solenium: sesión expirada"
            projs = r.json() if r.status_code == 200 else []
            projs = projs if isinstance(projs, list) else projs.get("results", [])

            # Resolve Solenium project ID
            sol_id = proyecto.project_id_solenium or ""
            if not sol_id:
                candidates = [
                    (proyecto.nombre_clientes or "").lower(),
                    (proyecto.nombre_bitacora or "").lower(),
                    (proyecto.nombre_comercial or "").lower(),
                    (proyecto.sub_project or "").lower(),
                ]
                for sp in projs:
                    sp_name = (sp.get("name") or sp.get("nombre") or "").lower()
                    sp_words = [w for w in sp_name.split() if len(w) > 2]
                    for cand in candidates:
                        if not cand:
                            continue
                        cand_words = [w for w in cand.split() if len(w) > 2]
                        if cand_words and sum(1 for w in cand_words if w in sp_name) / len(cand_words) >= 0.5:
                            sol_id = str(sp.get("id") or "")
                            break
                    if sol_id:
                        break

            if not sol_id:
                return [], "No se encontró el proyecto en Solenium (configura project_id_solenium en el proyecto)"

            # Step 2: get inverters
            r2 = await c.get(
                f"{settings.SOLENIUM_DATA_URL}/project/{sol_id}/inverter/",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r2.status_code != 200:
                return [], f"Solenium inversores HTTP {r2.status_code}"
            body = r2.json()
            inverters = body if isinstance(body, list) else body.get("results", body.get("inverters", []))
            return inverters, None
    except Exception as e:
        return [], str(e)


async def _action_get_fmo_data(sub_project: str | None, date_from: str | None, date_to: str | None, db: Session) -> dict:
    if not sub_project:
        return {"ok": False, "error": "sub_project requerido"}

    from sqlalchemy import or_
    proyecto = db.query(Proyecto).filter(
        or_(Proyecto.sub_project == sub_project, Proyecto.alias_monitoreo == sub_project)
    ).first()

    # Contract details
    contrato = None
    if proyecto:
        cs = (
            db.query(ContratoServicio)
            .filter(
                ContratoServicio.proyecto_id == proyecto.id,
                ContratoServicio.servicio_aplica == "operacion",
                ContratoServicio.estado.in_(["vigente", "en_renovacion"]),
            )
            .first()
        )
        if cs:
            contrato = {
                "sub_project": sub_project,
                "nombre_clientes": proyecto.nombre_clientes or proyecto.nombre_comercial,
                "disponibilidad_garantizada_pct": "97",
                "contratista": cs.prestador_nombre or "Unergy S.A.S.",
                "valor_estimado_ano1_cop": str(round(float(cs.tarifa_base) * 12)) if cs.tarifa_base else "0",
                "garantias_equipos": "",
                "numero_contrato": cs.numero_contrato or "",
            }

    # Maintenance records
    mantenimientos = []
    if proyecto:
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None
        except Exception:
            d_from = d_to = None
        mq = db.query(Mantenimiento).filter(Mantenimiento.proyecto_id == proyecto.id)
        if d_from:
            mq = mq.filter(Mantenimiento.fecha >= d_from)
        if d_to:
            mq = mq.filter(Mantenimiento.fecha <= d_to)
        for m in mq.order_by(Mantenimiento.fecha).all():
            mantenimientos.append({
                "id": m.id, "tipo": m.tipo or "", "descripcion": m.descripcion or "",
                "fecha": m.fecha.isoformat() if m.fecha else "",
                "estado": m.estado or "", "observaciones": m.observaciones or "",
            })

    # Inverters from Solenium
    inverters: list = []
    inverters_error: str | None = None
    if proyecto:
        inverters, inverters_error = await _solenium_inverters(proyecto)

    return {
        "ok": True,
        "contrato": contrato,
        "inverters": inverters,
        "inverters_error": inverters_error,
        "mantenimientos": mantenimientos,
    }


# ── Seed data: topic, nombre oficial, TSF, P50[ene..dic], P90[ene..dic] ───────
# Nombres y TSF extraídos del mapeo topic↔project y proyecto↔TSF compartido.
_SEED_PROYECTOS = [
    # (sub_project, nombre_oficial, codigo_tsf, p50[12], p90[12])
    ("verso",             "MGS 0008 La Paz Verso",        "COLCEST2P3",   [206181,197655,210695,155611,192449,193107,218885,203993,182065,162304,153812,207684], [191167,183262,195352,144279,178435,179045,202946,189138,168807,150485,142611,192560]),
    ("perija",            "MGS 0006 Perijá",               "COLCEST58P2",  [213966,223719,233630,214607,242503,241499,240207,224538,194680,175379,188780,235821], [202906,212155,221553,203514,229968,229016,227790,212931,184617,166313,179022,223631]),
    ("puya",              "MGS 0016 - Puya",               "COLCEST45P5",  [199700,232800,245000,227100,250100,253500,256900,238800,207400,174900,183100,244200], [187048,218051,229478,212712,234255,237440,240624,223671,194260,163819,171500,228729]),
    ("jerico_el_son",     "Minigranja Solar El Son",       "COLCEST45P1",  [252487,240733,233928,238064,233263,267168,270670,250967,217358,181428,198372,240864], [234101,223203,216893,220728,216277,247713,250960,232692,201530,168216,183927,223324]),
    ("elmolino",          "MGS 0009 El Molino",            "COLLAGT19P2",  [200772,150636,203829,192394,216277,190894,195267,206451,182565,147987,175731,203598], [186152,139667,188986,178384,200528,176993,181048,191417,169271,137211,162934,188772]),
    ("vallenata",         "MGS 0007 La Paz Vallenata",     "COLCEST9P1",   [246091,210697,249444,206881,234130,259056,261594,242907,214914,194310,205150,202767], [228786,195881,231903,192333,217666,240840,243199,225826,199802,180646,190724,188509]),
    ("villanueva",        "MGS 0010 - Villanueva",         "COLLAGT27P2",  [174832,186643,195820,168665,189603,186608,215995,203933,180583,170050,170417,198943], [156967,167571,175811,151431,170229,167540,193924,183095,162131,152674,153003,178615]),
    ("cañahuate",         "MGS 0005 Cañahuate",            "COLCEST61P1",  [247595,221129,248817,230879,261510,261747,237801,242671,211167,193666,192819,251923], [216886,193703,217956,202243,229075,229283,208307,212573,184976,169646,168904,220677]),
    ("gandalf",           "MGS 0004 Valle de Gandalf",     "COLCEST61P3",  [201758,193423,204798,191059,211782,212502,194000,182546,162850,157642,166494,202331], [176734,169433,179397,167362,185515,186146,169938,159905,142652,138090,145844,177236]),
    ("esmeralda",         "MGS 0017 Esmeralda",            "COLCEST17P1",  [209185,243783,253137,238505,245536,271718,247503,253708,216587,203251,215016,238358], [192544,224389,232999,219531,226003,250102,227813,233525,199357,187082,197911,219396]),
    ("lamesa",            "MGS 0013 La Mesa",              "COLSANT10P1",  [190900,171700,176000,180500,195200,179700,185700,181400,165900,166800,163400,193400], [177000,159198,163185,167357,180987,166615,172179,168192,153820,154655,151502,179318]),
    ("olimpo",            "MGS 0014 - El Olimpo",          "COLSANT4P2",   [183400,139000,168400,178400,192400,159600,170800,169900,164200,161400,162200,182300], [170043,128876,156135,165407,178387,147976,158360,157526,152241,149645,150387,169023]),
    ("reserva",           "Minigranja Solar La Palma",     "COLSANT9P1",   [241869,194044,228634,217270,222202,251027,261948,229577,205484,202765,203325,237037], [215828,173152,204018,193877,198278,224000,233745,204859,183360,180934,181434,211516]),
    ("uruaco_gd",         "Minigranja Solar Uruaco",       "COLATLT14P2",  [244124,231569,266507,242744,248162,236534,243712,238434,198697,196090,204872,231497], [211666,200781,231073,210470,215167,205085,211309,206733,172279,170019,177633,200718]),
    ("baraya",            "Minigranja Solar Baraya",       "COLSUCT17P2",  [248107,227365,251174,233011,225486,249967,252606,249039,205583,177108,216549,229822], [226033,207137,228827,212280,205425,227728,230132,226882,187292,161351,197283,209375]),
    ("leyenda",           "MGS 0018 La Paz Leyenda",       "COLCEST53P1",  [253311,244005,256516,210295,262780,206326,252976,250028,220754,188392,212067,259285], [234368,225758,237334,194569,243129,190897,234058,231331,204246,174304,196209,239896]),
    ("ibirico",           "MGS 0021 Ibirico",              "COLCEST49P2",  [229000,204400,252400,245900,259400,227100,258400,220800,209500,206000,212300,216100], [201524,179875,222116,216396,228276,199852,227396,194308,184364,181283,186828,190172]),
    ("cacica",            "MGS 0040 Cacica",               "COLCEST55P1",  [237322,222326,238786,217741,242920,245143,248063,233540,206816,184167,197056,238366], [217079,203362,218418,199168,222199,224233,226904,213619,189175,168458,180247,218034]),
    ("jerico_merengue",   "MGS 0019 El Merengue",          "COLCEST45P7",  [252609,246190,228221,238061,232811,267432,270919,251113,217430,181405,198054,240888], [194569,226750,235450,221841,228380,252733,230210,235982,201454,189050,199993,221704]),
    ("piloneras",         "MGS 0041 Piloneras",            "COLCEST55P2",  [237322,222326,238786,217741,242920,245143,248063,233540,206816,184167,197056,238366], [217079,203362,218418,199168,222199,224233,226904,213619,189175,168458,180247,218034]),
    ("cumbia",            "MGS 0022 - La Cumbia",          "COLCEST45P4",  [252747,246043,229042,209100,252234,246289,270706,250865,217134,198249,181487,238131], [235638,229387,213537,194945,235159,229617,252381,233883,202435,184829,169201,222011]),
    ("copey_occidente",   "MGS 0025 - El Copey Occidente", "COLCEST39P1",  [246438,209547,229367,238571,256862,254999,231928,242260,206926,188089,183973,241429], [223807,190304,208303,216662,233273,231582,210629,220012,187923,170816,167078,219258]),
    ("valenciaoriente",   "MGS 0026 Valencia Oriente 1",   "COLCEST74P1",  [195438,241270,253896,213443,258481,260767,235661,218270,211470,189944,205555,251316], [181206,223701,235407,197900,239658,241778,218500,202376,196071,176112,190586,233015]),
    ("valencia_oriente_2","MGS 0027 Valencia Oriente 2",   "COLCEST74P2",  [194987,240650,253374,213173,258077,260306,235288,218011,211189,189804,205292,250663], [183329,226262,238225,200428,242647,244743,221221,204977,198562,178456,193018,235676]),
    ("san_diego_sur",     "MGS 0024 - San Diego Sur",      "COLCEST38P1",  [0]*12, [0]*12),
]


# ── Mapeo completo topic → nombre oficial (106 proyectos Unergy) ──────────────
_TOPIC_MAP = {
    "zofiva": "Zona Franca V.A.",
    "yurbaqua": "PSF - Yurbaqua",
    "yuan_solar": "GD Yuan Solar",
    "villanueva": "MGS 0010 - Villanueva",
    "verso": "MGS 0008 La Paz Verso",
    "vallenata": "MGS 0007 La Paz Vallenata",
    "valenciaoriente": "MGS 0026 Valencia Oriente 1",
    "valencia_oriente_2": "MGS 0027 Valencia Oriente 2",
    "uruaco_gd": "Minigranja Solar Uruaco",
    "tierraalta": "Granja Solar Tierra Alta",
    "taurus_x": "Taurus X",
    "taurus_viii": "Taurus VIII",
    "taurus_ix": "Taurus IX",
    "tamalacue": "Minigranja Solar Tamalacué",
    "somer_torre_2": "Clínica Somer",
    "somer_torre_1": "Clínica Somer",
    "sirius": "GD Sirius",
    "seridme": "Seridme",
    "savannaplaza": "Centro Comercial Savanna Plaza",
    "sansimon": "Ladrillera Arcillas San Simón",
    "sanpedro": "Minigranja Solar San Pedro",
    "sanjose": "Centro de atención al desamparado San José",
    "sanesteban3": "San Esteban del Poblado",
    "sanesteban2": "San Esteban del Poblado",
    "sanesteban": "San Esteban del Poblado",
    "sanagustin_elektra": "GRANJA SOLAR SAN AGUSTIN",
    "san_pelayo": "GD San Pelayo",
    "san_onofre": "GD 1MVA SAN ONOFRE",
    "san_diego_sur": "MGS 0024 - San Diego Sur",
    "salud_vegas": "Salud Vegas - Torre Médica",
    "sabana_de_torres": "Minigranja Solar Sabana de Torres",
    "reserva": "Minigranja Solar La Palma",
    "puya": "MGS 0016 - Puya",
    "polikem": "Polikem",
    "polaris_2": "GD Polaris 2",
    "polaris_1": "GD Polaris 1",
    "poladelpub": "Pola del Pub",
    "piloneras": "MGS 0041 Piloneras",
    "perija": "MGS 0006 Perijá",
    "pazderio": "Triturados Paz de Río",
    "olimpo": "MGS 0014 - El Olimpo",
    "obelisco": "Centro Comercial Obelisco",
    "nuestroatlantico": "Centro Comercial Nuestro Atlántico",
    "ngs": "Nuevo Gimnasio School",
    "nestle_valledupar": "Nestlé Cicolac Valledupar",
    "naos3": "MGS Naos 3",
    "naos2": "MGS Naos 2",
    "naos1": "GD NAOS 1",
    "mdm": "MDM Científica",
    "marimonda": "GD Marimonda",
    "maderas": "Central de Maderas",
    "loscoches": "Los Coches",
    "leyenda": "MGS 0018 La Paz Leyenda",
    "laurelescampestre_parques": "Unidad Residencial Laureles Campestre",
    "laurelescampestre_fuentes_torre_3": "Unidad Residencial Laureles Campestre",
    "laurelescampestre_fuentes_torre_2": "Unidad Residencial Laureles Campestre",
    "laurelescampestre_aires_torre4": "Unidad Residencial Laureles Campestre",
    "laurelescampestre_aires_123": "Unidad Residencial Laureles Campestre",
    "lamesa": "MGS 0013 La Mesa",
    "joropo": "MGS 0023 Joropo",
    "jerico_merengue": "MGS 0019 El Merengue",
    "jerico_el_son": "Minigranja Solar El Son",
    "iml_etiquetas": "IML",
    "iml_empaques": "IML",
    "ibirico": "MGS 0021 Ibirico",
    "ibes": "Instituto Bolivariano Esdiseños",
    "gimsanangelo": "Gimnasio San Angelo",
    "gimcampreibri_comedor": "Gimnasio Campestre Reino Británico",
    "gimcampreibri_bloque4": "Gimnasio Campestre Reino Británico",
    "gandalf": "MGS 0004 Valle de Gandalf",
    "esmeralda": "MGS 0017 Esmeralda",
    "elroble": "MGS 0011 El Roble",
    "elmolino": "MGS 0009 El Molino",
    "ecoimagenips": "Ecoimagen IPS",
    "delta_2": "GD delta 2",
    "delta_1": "GD Delta 1",
    "cumbia": "MGS 0022 - La Cumbia",
    "cross": "Cross Business Center",
    "cristorey": "Colegio Cristo Rey Bogotá",
    "copey_occidente": "MGS 0025 - El Copey Occidente",
    "coopsana2": "IPS Coopsana",
    "coopsana": "IPS Coopsana",
    "colaboratec": "Colaboratec (Piloto)",
    "cienaga": "Sol&Cielo 9 - Ciénaga",
    "chiriguana_norte_4": "MGS 0077 - Chiriguaná Norte 4",
    "chiriguana_norte_2": "MGS 0075 - Chiriguaná Norte 2",
    "chima": "MGS 0030 Chimá Oriente",
    "cedillanosexc": "Cedillanos_excedentes",
    "cedillanos": "Complejo Industrial Cedillanos",
    "cañahuate": "MGS 0005 Cañahuate",
    "catedral": "La Catedral",
    "cacica": "MGS 0040 Cacica",
    "bongos": "Sol Y Cielo 7 Los Bongos",
    "biosolar": "GD Biosolar",
    "bayunca": "Bayunca",
    "baraya": "Minigranja Solar Baraya",
    "astrolumen": "GD Astrolumen La Garita",
    "asprolesa": "Asociación Asprolesa",
    "arboleda": "Arboleda de Castilla",
    "amc": "Almacenes AMC",
    "almagran": "Torre Almagrán",
    "agustin_3": "Agustín 3",
    "agustin_2": "Agustín 2",
    "agustin_1": "GD Agustin 1",
    "acanto": "Unidad Residencial Acanto",
}


@router.post("/_seed-topics")
def seed_topics(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Pobla sub_project en todos los proyectos usando el mapeo topic→nombre.
    Busca por nombre fuzzy; no sobreescribe si sub_project ya está seteado."""
    updated, not_found, skipped = [], [], []
    for topic, nombre in _TOPIC_MAP.items():
        # Skip if any project already has this topic assigned
        existing = db.query(Proyecto).filter(Proyecto.sub_project == topic).first()
        if existing:
            skipped.append({"topic": topic, "proyecto": existing.nombre_comercial})
            continue
        p = find_proyecto_by_name(db, nombre)
        if not p:
            not_found.append({"topic": topic, "nombre": nombre})
            continue
        p.sub_project = topic
        updated.append({"topic": topic, "nombre": nombre, "proyecto": p.nombre_comercial, "id": p.id})
    db.commit()
    return {"ok": True, "updated": updated, "skipped": skipped, "not_found": not_found}


@router.post("/_seed-p50p90")
def seed_p50_p90(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Seed sub_project, codigo_tsf y P50/P90 desde el mapeo del Apps Script.
    Busca por sub_project → alias_monitoreo → nombre fuzzy. Auto-asigna sub_project y TSF."""
    updated, not_found = [], []
    for sub, nombre_oficial, tsf, p50, p90 in _SEED_PROYECTOS:
        # 1. Exact match on sub_project or alias_monitoreo
        p = (
            db.query(Proyecto)
            .filter((Proyecto.sub_project == sub) | (Proyecto.alias_monitoreo == sub))
            .first()
        )
        # 2. Fallback: fuzzy match against nombre_oficial (from topic mapping)
        if not p:
            p = find_proyecto_by_name(db, nombre_oficial)
        if not p:
            not_found.append(sub)
            continue
        if not p.sub_project:
            p.sub_project = sub
        if not p.codigo_tsf:
            p.codigo_tsf = tsf
        p.p50_mensual_kwh = json.dumps(p50)
        p.p90_mensual_kwh = json.dumps(p90)
        updated.append({"sub": sub, "tsf": tsf, "proyecto": p.nombre_comercial, "id": p.id})
    db.commit()
    return {"ok": True, "updated": updated, "not_found": not_found}


@router.get("/_legacy")
async def legacy_bridge(
    action: str = Query(...),
    sub_project: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    if action == "getGeneration":
        return await _action_get_generation(sub_project, date_from, date_to, db)
    if action == "getProjects":
        return _action_get_projects(db)
    if action == "getPortfolios":
        return _action_get_portfolios(db)
    if action == "getAllContratos":
        return _action_get_all_contratos(db)
    if action == "getFMOData":
        return await _action_get_fmo_data(sub_project, date_from, date_to, db)
    if action == "sendCode":
        return {"ok": True}
    raise HTTPException(400, f"Acción no reconocida: {action}")


@router.post("/_legacy")
async def legacy_bridge_post(
    payload: dict,
    current_user: Usuario = Depends(get_current_user),
):
    action = payload.get("action", "")

    if action == "savePhoto":
        import base64
        import re
        from pathlib import Path as _Path

        fault_id = re.sub(r"[^\w\-]", "_", str(payload.get("faultId") or "unknown"))
        photo_name = re.sub(r"[^\w\-\.]", "_", str(payload.get("photoName") or "foto.jpg"))
        b64 = payload.get("b64") or ""
        mime = payload.get("mimeType") or "image/jpeg"

        ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
        ext = ext_map.get(mime, ".jpg")
        if not photo_name.lower().endswith(ext):
            photo_name = photo_name.rsplit(".", 1)[0] + ext

        try:
            img_bytes = base64.b64decode(b64)
        except Exception:
            return {"ok": False, "error": "Base64 inválido"}

        folder = _Path("uploads/fotos") / fault_id
        folder.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{photo_name}"
        (folder / filename).write_bytes(img_bytes)

        url = f"/static/uploads/fotos/{fault_id}/{filename}"
        return {"ok": True, "folderUrl": url, "photoUrl": url}

    if action == "sendCode":
        return {"ok": True}

    raise HTTPException(400, f"Acción POST no reconocida: {action}")


# ── Gestión de proyectos ───────────────────────────────────────────────────────

@router.get("/gestion/proyectos")
def gestion_list_proyectos(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.estado == "en_operacion")
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    result = []
    for p in proyectos:
        conteos = {
            "pqr": db.query(GestionRegistro).filter_by(proyecto_id=p.id, tipo="pqr").count(),
            "preventivo": db.query(GestionRegistro).filter_by(proyecto_id=p.id, tipo="preventivo").count(),
            "correctivo": db.query(GestionRegistro).filter_by(proyecto_id=p.id, tipo="correctivo").count(),
        }
        result.append({
            "id": p.id,
            "nombre": p.nombre_clientes or p.nombre_comercial,
            "nombre_comercial": p.nombre_comercial,
            "total_registros": sum(conteos.values()),
            "conteos": conteos,
        })
    return {"proyectos": result}


@router.get("/gestion/{proyecto_id}/registros")
def gestion_list_registros(
    proyecto_id: int,
    tipo: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(GestionRegistro).filter_by(proyecto_id=proyecto_id)
    if tipo:
        q = q.filter(GestionRegistro.tipo == tipo)
    registros = q.order_by(GestionRegistro.created_at.desc()).all()
    return {
        "registros": [
            {
                "id": r.id,
                "tipo": r.tipo,
                "titulo": r.titulo,
                "descripcion": r.descripcion or "",
                "archivos": json.loads(r.archivos_json) if r.archivos_json else [],
                "created_by": r.created_by or "",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in registros
        ]
    }


@router.post("/gestion/{proyecto_id}/registros", status_code=201)
def gestion_crear_registro(
    proyecto_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    tipo = (payload.get("tipo") or "pqr").strip()
    titulo = (payload.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(400, "El campo 'titulo' es requerido")
    if tipo not in ("pqr", "preventivo", "correctivo"):
        raise HTTPException(400, "tipo debe ser: pqr, preventivo o correctivo")

    archivos = payload.get("archivos") or []
    registro = GestionRegistro(
        proyecto_id=proyecto_id,
        tipo=tipo,
        titulo=titulo,
        descripcion=(payload.get("descripcion") or "").strip() or None,
        archivos_json=json.dumps(archivos) if archivos else None,
        created_by=current_user.nombre or current_user.email,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return {
        "ok": True,
        "id": registro.id,
        "tipo": registro.tipo,
        "titulo": registro.titulo,
        "created_at": registro.created_at.isoformat(),
    }


@router.delete("/gestion/registros/{registro_id}", status_code=200)
def gestion_eliminar_registro(
    registro_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    r = db.query(GestionRegistro).filter_by(id=registro_id).first()
    if not r:
        raise HTTPException(404, "Registro no encontrado")
    db.delete(r)
    db.commit()
    return {"ok": True}


# ── Correos de cliente ─────────────────────────────────────────────────────────

@router.get("/clientes")
def monitoreo_list_clientes(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    from app.models.clientes import Cliente
    clientes = db.query(Cliente).order_by(Cliente.razon_social_nombre).all()
    return {
        "clientes": [
            {
                "id": c.id,
                "nombre": c.razon_social_nombre,
                "correo_electronico": c.correo_electronico or "",
                "correo_liquidacion": c.correo_liquidacion or "",
                "correo_monitoreo": c.correo_monitoreo or "",
                "correo_soporte": c.correo_soporte or "",
            }
            for c in clientes
        ]
    }


@router.patch("/clientes/{cliente_id}/correos")
def monitoreo_update_correos(
    cliente_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    from app.models.clientes import Cliente
    c = db.query(Cliente).filter_by(id=cliente_id).first()
    if not c:
        raise HTTPException(404, "Cliente no encontrado")
    for field in ("correo_electronico", "correo_liquidacion", "correo_monitoreo", "correo_soporte"):
        if field in payload:
            setattr(c, field, (payload[field] or "").strip() or None)
    db.commit()
    return {
        "ok": True,
        "id": c.id,
        "correo_electronico": c.correo_electronico or "",
        "correo_liquidacion": c.correo_liquidacion or "",
        "correo_monitoreo": c.correo_monitoreo or "",
        "correo_soporte": c.correo_soporte or "",
    }
