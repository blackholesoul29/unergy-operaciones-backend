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
    GeneracionDiaria, MonitoreoVerificacion,
)
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto, Portafolio
from app.models.contratos import ContratoServicio
from app.models.mantenimientos import Mantenimiento
from app.utils.proyecto_matching import find_proyecto_by_name

router = APIRouter(prefix="/monitoreo", tags=["Monitoreo"])

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

    return {
        "id": f.codigo_interno,
        "proj": f.proyecto.nombre_comercial if f.proyecto else "",
        "code": f.tipo.codigo if f.tipo else "",
        "faultLabel": f.tipo.etiqueta if f.tipo else "",
        "st": st,
        "date": f.fecha_identificacion.isoformat() if f.fecha_identificacion else "",
        "time": f.hora_identificacion.strftime("%H:%M") if f.hora_identificacion else "",
        "occ": f.fecha_ocurrencia.strftime("%d/%m/%Y %H:%M") if f.fecha_ocurrencia else "",
        "res": f.resolucion.etiqueta if f.resolucion else "",
        "desc": f.descripcion or "",
        "flw": seguimiento_txt,
        "driUe": fotos_lista[0] if fotos_lista else "",
        "driUes": fotos_lista,
        "endDT": f.fecha_resolucion.strftime("%d/%m/%Y %H:%M") if f.fecha_resolucion else "",
        "centinela": f.centinela or "",
        "prio": f.prioridad.codigo if f.prioridad else "media",
        "notify": bool(f.notificacion),
        "photos": [],
        "_db_id": f.id,
        "_dias_abierta": f.dias_abierta,
        "_categoria_id": f.tipo.categoria.codigo if f.tipo and f.tipo.categoria else "",
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
    proyectos = (
        db.query(Proyecto)
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
        if p.cliente
        and getattr(p.cliente, "correo_electronico", None)
        and p.cliente.correo_electronico.lower() == email
    ]
    return {"ok": True, "projects": proyectos_cliente, "email": email}


# ── Legacy bridge — replaces Google Apps Script ───────────────────────────────

async def _unergy_token() -> str:
    auth_url = f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(auth_url, json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD})
        r.raise_for_status()
        data = r.json()
        return data.get("token") or data.get("key") or data.get("access") or ""


async def _fetch_unergy_raw(token: str, sub_project: str, date_from: str, date_to: str, verified_only: bool) -> list:
    params: dict = {
        "time_stamp__gte": date_from,
        "time_stamp__lte": date_to,
        "sub_project": sub_project,
        "limit": "10000",
    }
    if verified_only:
        params["verified_by_operator"] = "True"
    data_url = f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(data_url, params=params, headers={"Authorization": f"Token {token}"})
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("results", [])


def _compute_deltas(readings: list) -> list:
    readings.sort(key=lambda x: x.get("time_stamp") or x.get("timestamp") or "")
    result = []
    for i in range(1, len(readings)):
        prev, curr = readings[i - 1], readings[i]
        gen_curr = float(curr.get("generacion") or curr.get("generation") or 0)
        gen_prev = float(prev.get("generacion") or prev.get("generation") or 0)
        delta = max(0.0, gen_curr - gen_prev)
        ts_raw = curr.get("time_stamp") or curr.get("timestamp") or ""
        try:
            dt = (
                datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if "T" in ts_raw
                else datetime.strptime(ts_raw[:16], "%Y-%m-%d %H:%M")
            )
        except Exception:
            continue
        result.append({"time": dt.strftime("%Y-%m-%d %H:%M"), "date": dt.strftime("%Y-%m-%d"), "kwh": round(delta, 3)})
    return result


async def _action_get_generation(sub_project: str | None, date_from: str | None, date_to: str | None, db: Session) -> dict:
    if not sub_project:
        return {"ok": False, "error": "sub_project requerido"}

    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else date.today().replace(day=1)
        d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else date.today()
    except Exception:
        return {"ok": False, "error": "Formato de fecha inválido (YYYY-MM-DD)"}

    # Extend window by 2 days before to capture prior cumulative reading
    fetch_from = (d_from - timedelta(days=2)).strftime("%Y-%m-%d")
    fetch_to = (d_to + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        token = await _unergy_token()
        readings = await _fetch_unergy_raw(token, sub_project, fetch_from, fetch_to, verified_only=True)
        if not readings:
            readings = await _fetch_unergy_raw(token, sub_project, fetch_from, fetch_to, verified_only=False)
    except Exception as e:
        return {"ok": False, "error": f"Error API Unergy: {e}"}

    deltas = _compute_deltas(readings)
    d_from_str, d_to_str = d_from.strftime("%Y-%m-%d"), d_to.strftime("%Y-%m-%d")
    filtered = [d for d in deltas if d_from_str <= d["date"] <= d_to_str]

    # P50/P90 simulation from project record
    simulation = None
    proyecto = db.query(Proyecto).filter(Proyecto.sub_project == sub_project).first()
    if proyecto and (proyecto.p90_mensual_kwh or proyecto.p50_mensual_kwh):
        try:
            month = d_from.month
            p90_list = json.loads(proyecto.p90_mensual_kwh) if proyecto.p90_mensual_kwh else [None] * 12
            p50_list = json.loads(proyecto.p50_mensual_kwh) if proyecto.p50_mensual_kwh else [None] * 12
            p90m = p90_list[month - 1] if len(p90_list) >= month else None
            p50m = p50_list[month - 1] if len(p50_list) >= month else None
            days_in_month = calendar.monthrange(d_from.year, month)[1]
            simulation = {
                "p90_monthly": p90m,
                "p50_monthly": p50m,
                "p90_daily": round(p90m / days_in_month, 1) if p90m else None,
            }
        except Exception:
            pass

    return {"ok": True, "data": filtered, "simulation": simulation}


def _action_get_projects(db: Session) -> dict:
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.sub_project.isnot(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return {
        "ok": True,
        "projects": [
            {
                "sub_project": p.sub_project,
                "nombre_comercial": p.nombre_comercial,
                "nombre_clientes": p.nombre_clientes or p.nombre_comercial,
                "nombre_bitacora": p.nombre_bitacora or "",
                "nombre_display": p.nombre_clientes or p.nombre_bitacora or p.nombre_comercial,
                "municipio": p.municipio or "—",
                "departamento": p.departamento or "—",
                "potencia_instalada_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp else None,
                "estado": p.estado,
            }
            for p in proyectos
        ],
    }


def _action_get_portfolios(db: Session) -> dict:
    portafolios = db.query(Portafolio).filter(Portafolio.activo == True).all()
    portfolios: dict = {}
    for pf in portafolios:
        names = [p.nombre_clientes or p.nombre_comercial for p in pf.proyectos if p.sub_project]
        if names:
            portfolios[pf.nombre] = names
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
        if not p or not p.sub_project:
            continue
        contratos.append({
            "sub_project": p.sub_project,
            "nombre_clientes": p.nombre_clientes or p.nombre_comercial,
            "disponibilidad_garantizada_pct": "97",
            "contratista": c.prestador_nombre or "Unergy S.A.S.",
            "valor_estimado_ano1_cop": str(round(float(c.tarifa_base) * 12)) if c.tarifa_base else "0",
            "garantias_equipos": "",
            "numero_contrato": c.numero_contrato or "",
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else "",
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else "",
        })
    return {"ok": True, "contratos": contratos}


async def _action_get_fmo_data(sub_project: str | None, date_from: str | None, date_to: str | None, db: Session) -> dict:
    if not sub_project:
        return {"ok": False, "error": "sub_project requerido"}

    proyecto = db.query(Proyecto).filter(Proyecto.sub_project == sub_project).first()

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
                "id": m.id,
                "tipo": m.tipo or "",
                "descripcion": m.descripcion or "",
                "fecha": m.fecha.isoformat() if m.fecha else "",
                "estado": m.estado or "",
                "observaciones": m.observaciones or "",
            })

    # Inverter data from Solenium (optional)
    inverters: list = []
    inverters_error: str | None = None
    if settings.SOLENIUM_API_KEY and proyecto and proyecto.project_id_solenium:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(
                    f"https://api.solenium.co/v1/projects/{proyecto.project_id_solenium}/inverters",
                    headers={"Authorization": f"Bearer {settings.SOLENIUM_API_KEY}"},
                    params={"date_from": date_from or "", "date_to": date_to or ""},
                )
                if r.status_code == 200:
                    body = r.json()
                    inverters = body if isinstance(body, list) else body.get("results", [])
                else:
                    inverters_error = f"Solenium HTTP {r.status_code}"
        except Exception as e:
            inverters_error = str(e)

    return {
        "ok": True,
        "contrato": contrato,
        "inverters": inverters,
        "inverters_error": inverters_error,
        "mantenimientos": mantenimientos,
    }


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
