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
import json
import random
import string
from datetime import datetime, date, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import (
    Falla, FallaSeguimiento,
    FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria, FallaCatResolucion,
    GeneracionDiaria, MonitoreoVerificacion,
)
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto
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
    selectinload(Falla.seguimientos).options(
        selectinload(FallaSeguimiento.usuario),
        selectinload(FallaSeguimiento.estado_nuevo),
    ),
]


# ── Helper ────────────────────────────────────────────────────────────────────

def _falla_to_fault(f: Falla) -> dict:
    st = _CODIGO_A_ST.get(f.estado.codigo if f.estado else "abierta", "activa")

    seguimiento_txt = ""
    if f.seguimientos:
        lineas = []
        for seg in sorted(f.seguimientos, key=lambda s: s.created_at):
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
            segs_sorted = sorted(falla.seguimientos, key=lambda s: s.created_at)
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
        .filter(Proyecto.estado == "en_operacion")
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
