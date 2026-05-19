"""
Endpoints de compatibilidad para fallas-unergy.
Traduce entre el formato de la app vanilla-JS y nuestra base de datos PostgreSQL.

Convención de estados:
  fallas-unergy  ←→  FallaCatEstado.codigo
  activa         ←→  abierta
  revision       ←→  en_gestion
  programada     ←→  en_espera
  terminada      ←→  cerrada / sin_solucion (ambos → terminada al salir)
"""
import calendar
import json
import random
import string
from datetime import datetime, date, time as time_type, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy.orm import Session, selectinload
from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import (
    Falla, FallaSeguimiento, FallaCatEstado, FallaCatPrioridad,
    FallaCatTipo, FallaCatCategoria, FallaCatResolucion, GeneracionDiaria,
    MonitoreoVerificacion, Portafolio, ContratoServicio, Mantenimiento,
)
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto
from app.utils.proyecto_matching import find_proyecto_by_name

router = APIRouter(prefix="/monitoreo", tags=["Monitoreo"])

# ── mapeos de estado ──────────────────────────────────────────────────────────
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

_FALLA_EAGER = [
    selectinload(Falla.proyecto),
    selectinload(Falla.tipo).selectinload(FallaCatTipo.categoria),
    selectinload(Falla.estado),
    selectinload(Falla.prioridad),
    selectinload(Falla.resolucion),
    selectinload(Falla.registrado_por),
    selectinload(Falla.asignado_a),
    selectinload(Falla.seguimientos).options(
        selectinload(FallaSeguimiento.usuario),
        selectinload(FallaSeguimiento.estado_nuevo),
    ),
]


def _falla_to_fault(f: Falla) -> dict:
    """Serializa una Falla de PostgreSQL al formato interno de fallas-unergy."""
    st = _CODIGO_A_ST.get(f.estado.codigo if f.estado else "abierta", "activa")

    # construir seguimiento acumulado (mismo formato que Google Sheets)
    seguimiento_txt = ""
    if f.seguimientos:
        lineas = []
        for seg in sorted(f.seguimientos, key=lambda s: s.created_at):
            ts = seg.created_at.strftime("%d/%m/%Y %H:%M") if seg.created_at else ""
            quien = seg.usuario.nombre if seg.usuario else "—"
            nota = seg.nota or ""
            lineas.append(f"{ts} - {quien}: {nota}")
        seguimiento_txt = "\n".join(lineas)

    fotos_lista: list[str] = f.fotos_urls or []

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
        "driveUrl": fotos_lista[0] if fotos_lista else "",
        "driveUrls": fotos_lista,
        "endDT": f.fecha_resolucion.strftime("%d/%m/%Y %H:%M") if f.fecha_resolucion else "",
        "centinela": f.centinela or "",
        "prio": f.prioridad.codigo if f.prioridad else "media",
        "notify": bool(f.notificacion),
        "photos": [],
        # campos extra útiles para el frontend
        "_db_id": f.id,
        "_dias_abierta": f.dias_abierta,
        "_categoria_id": str(f.tipo.categoria.codigo) if f.tipo and f.tipo.categoria else "",
        "_categoria_lbl": f.tipo.categoria.etiqueta if f.tipo and f.tipo.categoria else "",
    }


# ── GET /monitoreo/fallas ─────────────────────────────────────────────────────
@router.get("/fallas")
def get_fallas_monitoreo(
    proyecto_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Devuelve las fallas en el formato esperado por fallas-unergy."""
    q = db.query(Falla).options(*_FALLA_EAGER)

    # si el usuario es de rol cliente, filtrar solo sus proyectos
    if current_user.rol.value == "solo_lectura":
        # TODO: filtrar por proyectos del cliente cuando se implemente
        pass

    if proyecto_id:
        q = q.filter(Falla.proyecto_id == proyecto_id)

    fallas = q.order_by(Falla.created_at.desc()).all()
    results = []
    errors = []
    for f in fallas:
        try:
            results.append(_falla_to_fault(f))
        except Exception as e:
            errors.append({"id": f.id, "error": str(e)})
    return {"ok": True, "faults": results, "errors": errors}



# ── POST /monitoreo/fallas/save ───────────────────────────────────────────────
@router.post("/fallas/save")
def save_falla_monitoreo(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Crea o actualiza una falla desde fallas-unergy."""
    fault_id: str = payload.get("id", "").strip()
    is_new = not fault_id

    # ── resolver proyecto ─────────────────────────────────────────────────
    proyecto: Proyecto | None = None
    nombre_proyecto = payload.get("project", "").strip()
    if nombre_proyecto:
        proyecto = find_proyecto_by_name(db, nombre_proyecto)
    if not proyecto:
        raise HTTPException(400, f"No se encontró proyecto para '{nombre_proyecto}'")

    # ── resolver estado ───────────────────────────────────────────────────
    st_code = _ST_A_CODIGO.get(payload.get("status", "activa"), "abierta")
    estado = db.query(FallaCatEstado).filter(FallaCatEstado.codigo == st_code).first()
    if not estado:
        raise HTTPException(400, f"Estado no reconocido: {st_code}")

    # ── resolver tipo de falla ────────────────────────────────────────────
    fault_code = payload.get("faultCode", "").strip()
    tipo = db.query(FallaCatTipo).filter(FallaCatTipo.codigo == fault_code).first()
    if not tipo:
        # fallback: primer tipo disponible de la categoría (por ID numérico)
        cat_id_str = str(payload.get("categoryId", "1"))
        cat = db.query(FallaCatCategoria).filter(FallaCatCategoria.codigo == cat_id_str).first()
        tipo = (
            db.query(FallaCatTipo)
            .filter(FallaCatTipo.categoria_id == cat.id, FallaCatTipo.activa == True)
            .first()
            if cat else None
        )
        if not tipo:
            raise HTTPException(400, f"Tipo de falla no reconocido: {fault_code}")

    # ── resolver prioridad ────────────────────────────────────────────────
    prio_codigo = (payload.get("prioridad") or "media").lower()
    prioridad = db.query(FallaCatPrioridad).filter(FallaCatPrioridad.codigo == prio_codigo).first()
    if not prioridad:
        prioridad = db.query(FallaCatPrioridad).order_by(FallaCatPrioridad.nivel).first()

    # ── resolver resolución ───────────────────────────────────────────────
    resolucion = None
    res_texto = (payload.get("resType") or "").strip()
    if res_texto:
        resolucion = db.query(FallaCatResolucion).filter(
            FallaCatResolucion.etiqueta.ilike(f"%{res_texto}%")
        ).first()

    # ── parsear fechas ─────────────────────────────────────────────────────
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
        for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _parse_time_val(s: str) -> time_type | None:
        if not s or not s.strip():
            return None
        try:
            parts = s.strip().split(":")
            return time_type(int(parts[0]), int(parts[1]))
        except Exception:
            return None

    fecha_id = _parse_date(payload.get("identDate", "")) or date.today()
    hora_id = _parse_time_val(payload.get("identTime", ""))
    fecha_ocurrencia = _parse_datetime(payload.get("occTime", ""))
    fecha_resolucion = _parse_datetime(payload.get("endTime", ""))

    # ── fotos: solo almacenar URLs, no subir nada ─────────────────────────
    fotos_urls_payload = payload.get("driveUrls") or []
    # Defensivo: el frontend podría enviar driveUrls como JSON-string (doble-encoding)
    if isinstance(fotos_urls_payload, str):
        try:
            fotos_urls_payload = json.loads(fotos_urls_payload)
            if not isinstance(fotos_urls_payload, list):
                fotos_urls_payload = []
        except Exception:
            fotos_urls_payload = []
    drive_url = payload.get("driveUrl", "").strip()
    if drive_url and drive_url not in fotos_urls_payload:
        fotos_urls_payload = [drive_url] + fotos_urls_payload
    fotos_json = fotos_urls_payload if fotos_urls_payload else None

    centinela = (payload.get("centinela") or "").strip() or current_user.nombre
    followup_nuevo = (payload.get("followUp") or "").strip()

    if is_new:
        # ── crear nueva falla ─────────────────────────────────────────────
        from datetime import timezone as tz
        from sqlalchemy import func as sqlfunc
        year = datetime.now(tz.utc).year
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
            hora_identificacion=hora_id,
            fecha_ocurrencia=fecha_ocurrencia,
            fecha_resolucion=fecha_resolucion,
            fotos_urls=fotos_json,
            centinela=centinela,
            notificacion=bool(payload.get("notify", False)),
        )
        db.add(falla)
        db.flush()  # obtener ID

        if followup_nuevo:
            seg = FallaSeguimiento(
                falla_id=falla.id,
                usuario_id=current_user.id,
                nota=followup_nuevo,
            )
            db.add(seg)
    else:
        # ── actualizar falla existente ────────────────────────────────────
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
        if hora_id is not None:
            falla.hora_identificacion = hora_id
        falla.fecha_ocurrencia = fecha_ocurrencia
        falla.fecha_resolucion = fecha_resolucion
        falla.fotos_urls = fotos_json
        falla.centinela = centinela
        falla.notificacion = bool(payload.get("notify", False))

        # agregar seguimiento solo si el texto cambió respecto al último
        if followup_nuevo:
            segs_existentes = [
                s for s in sorted(falla.seguimientos, key=lambda s: s.created_at)
            ]
            ultimo_flw = segs_existentes[-1].nota if segs_existentes else ""
            if followup_nuevo != ultimo_flw:
                seg = FallaSeguimiento(
                    falla_id=falla.id,
                    usuario_id=current_user.id,
                    nota=followup_nuevo,
                    estado_nuevo_id=estado.id,
                )
                db.add(seg)

    db.commit()

    # recargar con eager loading para respuesta
    falla_out = (
        db.query(Falla)
        .options(*_FALLA_EAGER)
        .filter(Falla.codigo_interno == (falla.codigo_interno if is_new else fault_id))
        .first()
    )
    return {"ok": True, "fault": _falla_to_fault(falla_out)}


# ── POST /monitoreo/fallas/delete ─────────────────────────────────────────────
@router.post("/fallas/delete")
def delete_falla_monitoreo(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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


# ── PATCH /monitoreo/mantenimientos/{id} ─────────────────────────────────────
@router.patch("/mantenimientos/{mant_id}")
def patch_mantenimiento(
    mant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    m = db.query(Mantenimiento).filter(Mantenimiento.id == mant_id).first()
    if not m:
        raise HTTPException(404, f"Mantenimiento {mant_id} no encontrado")

    if payload.get("fecha"):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                m.fecha = datetime.strptime(payload["fecha"].strip(), fmt).date()
                break
            except ValueError:
                continue
    if payload.get("tipo"):
        m.tipo = payload["tipo"]
    if payload.get("descripcion"):
        m.descripcion = payload["descripcion"]
    if payload.get("estado"):
        m.estado = payload["estado"]
    if "observaciones" in payload:
        m.observaciones = payload["observaciones"] or None

    db.commit()
    db.refresh(m)
    return {
        "ok": True,
        "mantenimiento": {
            "id": m.id,
            "tipo": m.tipo or "",
            "descripcion": m.descripcion or "",
            "fecha": m.fecha.isoformat() if m.fecha else "",
            "estado": m.estado or "",
            "observaciones": m.observaciones or "",
        },
    }


# ── GET /monitoreo/catalogo ───────────────────────────────────────────────────
@router.get("/catalogo")
def get_catalogo(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Devuelve el catálogo de fallas en el formato DEFAULT_CATS de fallas-unergy."""
    categorias = (
        db.query(FallaCatCategoria)
        .options(selectinload(FallaCatCategoria.tipos))
        .filter(FallaCatCategoria.activa == True)
        .order_by(FallaCatCategoria.orden)
        .all()
    )
    result = []
    for cat in categorias:
        tipos_activos = [t for t in cat.tipos if t.activa]
        result.append({
            "id": cat.codigo,
            "lbl": cat.etiqueta,
            "ico": cat.icono or "📋",
            "col": cat.color_hex or "#915BD8",
            "faults": [
                {"code": t.codigo, "label": t.etiqueta, "desc": t.descripcion or ""}
                for t in sorted(tipos_activos, key=lambda t: t.codigo)
            ],
        })
    return result


# ── GET /monitoreo/proyectos ──────────────────────────────────────────────────
@router.get("/proyectos")
def get_proyectos_monitoreo(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Devuelve proyectos en operación con su cliente (inversionista), para poblar selectores."""
    from sqlalchemy import or_ as _or2
    from app.models.clientes import Cliente as ClienteM
    from app.models.proyectos import ProyectoInversionista

    # Todos los proyectos (para mapeo cliente↔proyecto en fallas)
    all_proyectos = (
        db.query(Proyecto)
        .options(
            selectinload(Proyecto.inversionistas).selectinload(ProyectoInversionista.cliente),
            selectinload(Proyecto.cliente),
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    # Solo proyectos en operación para los selectores de generación
    op_proyectos = [
        p for p in all_proyectos
        if p.srv_operacion or p.estado == "en_operacion"
    ]
    clientes = db.query(ClienteM).order_by(ClienteM.razon_social_nombre).all()

    def _get_cliente_nombres(p: Proyecto) -> list[str]:
        names: list[str] = []
        invs = p.inversionistas
        if not isinstance(invs, list):
            invs = [invs] if invs is not None else []
        for inv in invs:
            if inv.cliente and inv.cliente.razon_social_nombre:
                n = inv.cliente.razon_social_nombre
                if n not in names:
                    names.append(n)
        if not names and p.cliente and p.cliente.razon_social_nombre:
            names.append(p.cliente.razon_social_nombre)
        return names

    return {
        "proyectos": [p.nombre_comercial for p in op_proyectos],
        "proyectos_detalle": [
            {
                "id": p.id,
                "nombre": p.nombre_comercial,
                "alias": p.alias_monitoreo or "",
                "sub_project": p.sub_project or p.alias_monitoreo or "",
                "cliente_nombre": _get_cliente_nombres(p)[0] if _get_cliente_nombres(p) else "",
                "cliente_nombres": _get_cliente_nombres(p),  # todos los clientes del proyecto
            }
            for p in all_proyectos  # todos, para cubrir cualquier proyecto con fallas
        ],
        "clientes": [
            {"id": c.id, "nombre": c.razon_social_nombre}
            for c in clientes
        ],
    }


# ── GET /monitoreo/generacion ─────────────────────────────────────────────────
@router.get("/generacion")
def get_generacion_monitoreo(
    proyecto_nombre: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Devuelve datos de generación para el panel de generación de fallas-unergy."""
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


# ── POST /monitoreo/auth/verify-email ────────────────────────────────────────
@router.post("/auth/verify-email")
def verify_email_monitoreo(payload: dict, db: Session = Depends(get_db)):
    """Valida que un email @unergy.io tenga usuario en la plataforma y devuelve un JWT.
    Restringido a dominio corporativo. Usado por fallas-unergy cuando no viene token."""
    from app.core.security import create_access_token
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email requerido")

    if not email.endswith("@unergy.io"):
        raise HTTPException(403, "Solo correos @unergy.io pueden usar este método")

    user = db.query(Usuario).filter(Usuario.email == email, Usuario.activo == True).first()
    if not user:
        return {"ok": False, "msg": "Correo no registrado en la plataforma"}

    token = create_access_token({
        "sub": str(user.id),
        "rol": user.rol.value,
        "nombre": user.nombre,
        "email": user.email,
    })
    return {
        "ok": True,
        "nombre": user.nombre,
        "email": user.email,
        "rol": user.rol.value,
        "token": token,
    }


# ── POST /monitoreo/auth/send-code ────────────────────────────────────────────
@router.post("/auth/send-code")
def send_code(payload: dict, db: Session = Depends(get_db)):
    """Genera y almacena un código de 6 dígitos para acceso de clientes.
    El envío del email debe configurarse con SMTP/SendGrid en producción."""
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Email requerido")

    codigo = "".join(random.choices(string.digits, k=6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # invalidar códigos anteriores del mismo email
    db.query(MonitoreoVerificacion).filter(
        MonitoreoVerificacion.email == email,
        MonitoreoVerificacion.usado == False,
    ).delete()

    verificacion = MonitoreoVerificacion(
        email=email,
        codigo=codigo,
        expires_at=expires_at,
    )
    db.add(verificacion)
    db.commit()

    # TODO: integrar envío real de email (SendGrid / SES / SMTP)
    # Por ahora, el código se puede ver en los logs de desarrollo
    print(f"[MONITOREO] Código para {email}: {codigo}")

    return {"ok": True}


# ── POST /monitoreo/auth/verify-code ─────────────────────────────────────────
@router.post("/auth/verify-code")
def verify_code(payload: dict, db: Session = Depends(get_db)):
    """Verifica el código de 6 dígitos y devuelve los proyectos del cliente."""
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

    # buscar proyectos asociados al email del cliente
    proyectos = (
        db.query(Proyecto)
        .join(Proyecto.cliente)
        .filter(
            Proyecto.estado == "en_operacion",
        )
        .all()
    )
    # filtrar proyectos donde el cliente tiene correo coincidente
    proyectos_cliente = [
        p.nombre_comercial for p in proyectos
        if p.cliente and p.cliente.correo and p.cliente.correo.lower() == email
    ]

    return {"ok": True, "projects": proyectos_cliente, "email": email}


# ── Legacy bridge — replaces Google Apps Script ───────────────────────────────

_COL_TZ = timezone(timedelta(hours=-5))

# ── Unergy API helpers ────────────────────────────────────────────────────────

_token_cache: dict = {"token": "", "expires_at": 0.0}

async def _unergy_token() -> str:
    import time as _time
    now = _time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]
    auth_url = f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(auth_url, json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD})
        r.raise_for_status()
        data = r.json()
        tok = data.get("token") or data.get("access") or data.get("key") or ""
        if tok:
            _token_cache["token"] = tok
            _token_cache["expires_at"] = now + 300  # reuse for 5 minutes
        return tok


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

    d_from_dt = datetime(d_from_date.year, d_from_date.month, d_from_date.day, 0, 0, 0, tzinfo=_COL_TZ)
    d_to_dt = datetime(d_to_date.year, d_to_date.month, d_to_date.day, 23, 59, 59, tzinfo=_COL_TZ)
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

    simulation = None
    from sqlalchemy import or_
    import json as _json

    def _parse_kwh_list(val):
        """Normaliza JSONB o string JSON a list[float|None]. Maneja datos históricos."""
        if val is None:
            return None
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            try:
                result = _json.loads(val)
                return result if isinstance(result, list) else None
            except Exception:
                return None
        return None

    proyecto = db.query(Proyecto).filter(
        or_(Proyecto.sub_project == sub_project, Proyecto.alias_monitoreo == sub_project)
    ).first()
    if proyecto and (proyecto.p90_mensual_kwh or proyecto.p50_mensual_kwh):
        try:
            month = d_from_date.month
            p90_list = _parse_kwh_list(proyecto.p90_mensual_kwh) or [None] * 12
            p50_list = _parse_kwh_list(proyecto.p50_mensual_kwh) or [None] * 12
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
    """Clientes (inversionistas) con proyectos en operación, agrupados por cliente."""
    try:
        from sqlalchemy import or_
        from app.models.proyectos import ProyectoInversionista

        # Consultar directo desde la tabla de inversionistas
        rows = (
            db.query(ProyectoInversionista)
            .join(ProyectoInversionista.proyecto)
            .filter(
                or_(Proyecto.srv_operacion == True, Proyecto.estado == "en_operacion")  # noqa: E712
            )
            .options(
                selectinload(ProyectoInversionista.cliente),
                selectinload(ProyectoInversionista.proyecto),
            )
            .all()
        )
        portfolios: dict = {}
        for inv in rows:
            if not inv.cliente or not inv.proyecto:
                continue
            p = inv.proyecto
            proj_name = p.nombre_comercial  # usar nombre_comercial para coincidir con f.proj en el frontend
            cliente_nombre = inv.cliente.razon_social_nombre
            portfolios.setdefault(cliente_nombre, [])
            if proj_name not in portfolios[cliente_nombre]:
                portfolios[cliente_nombre].append(proj_name)

        # Fallback: proyectos con cliente_id directo no cubiertos por inversionistas
        if not portfolios:
            proyectos = (
                db.query(Proyecto)
                .filter(
                    or_(Proyecto.srv_operacion == True, Proyecto.estado == "en_operacion")  # noqa: E712
                )
                .options(selectinload(Proyecto.cliente))
                .all()
            )
            for p in proyectos:
                if p.cliente:
                    nombre = p.cliente.razon_social_nombre
                    proj_name = p.nombre_comercial
                    portfolios.setdefault(nombre, [])
                    if proj_name not in portfolios[nombre]:
                        portfolios[nombre].append(proj_name)

        return {"ok": True, "portfolios": portfolios}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(exc), "portfolios": {}}


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
    for cs in rows:
        p = cs.proyecto
        slug = (p.sub_project or p.alias_monitoreo) if p else None
        if not slug:
            continue
        contratos.append({
            "sub_project": slug,
            "nombre_clientes": p.nombre_clientes or p.nombre_comercial,
            "disponibilidad_garantizada_pct": "97",
            "contratista": cs.prestador_nombre or "Unergy S.A.S.",
            "valor_estimado_ano1_cop": str(round(float(cs.tarifa_base) * 12)) if cs.tarifa_base else "0",
            "garantias_equipos": "",
            "numero_contrato": cs.numero_contrato or "",
            "fecha_inicio": cs.fecha_inicio.isoformat() if cs.fecha_inicio else "",
            "fecha_fin": cs.fecha_fin.isoformat() if cs.fecha_fin else "",
            "project_id_solenium": p.project_id_solenium or "",
        })
    return {"ok": True, "contratos": contratos}


# ── Solenium token cache ──────────────────────────────────────────────────────
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


# ── GET /monitoreo/_legacy ────────────────────────────────────────────────────
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


# ── POST /monitoreo/_legacy ───────────────────────────────────────────────────
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

        from pathlib import Path as _Path
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


# ── POST /monitoreo/admin/sync-proyectos (temporal) ───────────────────────────
@router.post("/admin/sync-proyectos")
def sync_proyectos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Llena campos faltantes de proyectos desde proyectos_solares_completo.json
    y aplica el mapeo de Operadores de Red. Solo admin."""
    if current_user.rol.value not in ("admin", "operaciones"):
        raise HTTPException(403, "Sin permisos")

    import json as _json
    import re as _re
    from pathlib import Path as _Path
    from app.models.proyectos import ProyectoInfoTecnica

    OR_MAP = {
        "Perija": "Afinia", "El son": "Afinia", "Molino": "Air-e",
        "La Puya": "Afinia", "Villanueva": "Air-e", "Reserva": "ESSA",
        "Cañahuate": "Afinia", "La Paz Leyenda": "Afinia", "La Paz Verso": "Afinia",
        "San Pedro": "Afinia", "La Paz Vallenata": "Afinia", "Gandalf": "Afinia",
        "Uruaco": "Air-e", "Baraya": "Afinia", "La Paz Esmeralda": "Afinia",
        "El merengue": "Afinia", "El Olimpo": "ESSA", "Ibirico": "Afinia",
        "La Mesa": "ESSA", "San Diego Sur": "Afinia", "La Cacica 2": "Afinia",
        "La Molina": "Afinia", "La Cumbia": "Afinia",
        "Valencia 1": "Afinia", "Valencia 2": "Afinia",
    }
    NOMBRE_MAP = {
        "MGS 0004 Valle de Gandalf": "Gandalf",
        "MGS 0005 Cañahuate": "Cañahuate",
        "MGS 0006 Perijá": "Perija",
        "MGS 0007 La Paz Vallenata": "La Paz Vallenata",
        "MGS 0008 La Paz Verso": "La Paz Verso",
        "MGS 0009 El Molino": "Molino",
        "MGS 0010 - Villanueva": "Villanueva",
        "MGS 0011 El Roble": "El Roble",
        "MGS 0013 La Mesa": "La Mesa",
        "MGS 0014 - El Olimpo": "El Olimpo",
        "MGS 0016 - Puya": "La Puya",
        "MGS 0017- Esmeralda": "Esmeralda",
        "MGS 0018 La Paz Leyenda": "La Paz Leyenda",
        "MGS 0019 El Merengue": "merengue",
        "Complejo Industrial Cedillanos": "Cedillanos",
        "GRANJA SOLAR SAN AGUSTIN": "San Agustin",
    }

    def _find(kw):
        r = db.query(Proyecto).filter(Proyecto.nombre_comercial == kw).first()
        if r: return r
        r = db.query(Proyecto).filter(Proyecto.nombre_comercial.ilike(f"%{kw}%")).first()
        if r: return r
        r = db.query(Proyecto).filter(Proyecto.alias_monitoreo.ilike(f"%{kw}%")).first()
        return r

    def _clean_dpto(s):
        return _re.sub(r"\s+[Dd]epartment$", "", (s or "").strip()).strip()

    def _upsert_it(pid, n):
        it = db.query(ProyectoInfoTecnica).filter(ProyectoInfoTecnica.proyecto_id == pid).first()
        if it:
            if not it.cantidad_total_paneles:
                it.cantidad_total_paneles = n
        else:
            db.add(ProyectoInfoTecnica(proyecto_id=pid, cantidad_total_paneles=n))

    json_path = _Path(__file__).parent.parent.parent.parent / "data" / "proyectos_solares_completo.json"
    data = _json.loads(json_path.read_text(encoding="utf-8"))

    updated, skipped = [], []

    for row in data:
        nombre = row.get("nombre_topico", "").strip()
        kw = NOMBRE_MAP.get(nombre) or _re.sub(r"^MGS\s*\d+\s*[-\s]*", "", nombre).strip() or nombre
        proj = _find(kw)
        if not proj:
            skipped.append(nombre)
            continue
        changed = False
        dpto = _clean_dpto(row.get("departamento") or "")
        if dpto and not proj.departamento:
            proj.departamento = dpto; changed = True
        ciudad = (row.get("ciudad") or "").strip()
        if ciudad and not proj.municipio:
            proj.municipio = ciudad; changed = True
        kwp = row.get("potencia_instalada_dc_kwp")
        if kwp is not None and not proj.potencia_instalada_kwp:
            proj.potencia_instalada_kwp = kwp; changed = True
        paneles = row.get("numero_de_paneles")
        if paneles is not None and not proj.cantidad_total_paneles:
            proj.cantidad_total_paneles = paneles
            _upsert_it(proj.id, paneles); changed = True
        if changed:
            updated.append(proj.nombre_comercial)

    or_updated, or_skipped = [], []
    for kw, operador in OR_MAP.items():
        proj = _find(kw)
        if not proj:
            or_skipped.append(kw); continue
        if not proj.operador_red or proj.operador_red.strip() != operador:
            proj.operador_red = operador
            or_updated.append(proj.nombre_comercial)

    db.commit()
    return {
        "ok": True,
        "json_actualizados": updated,
        "json_saltados": skipped,
        "or_actualizados": or_updated,
        "or_saltados": or_skipped,
    }
