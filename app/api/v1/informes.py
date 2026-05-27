"""
CRUD y flujo de aprobación de informes generados en el módulo de monitoreo.

Endpoints:
  POST   /api/v1/informes/              — crear o actualizar (upsert por tipo+sub_project+periodo)
  GET    /api/v1/informes/              — listar (filtros opcionales)
  GET    /api/v1/informes/{id}          — detalle
  PATCH  /api/v1/informes/{id}/estado   — cambiar estado (revisado / aprobado)
  POST   /api/v1/informes/{id}/enviar   — enviar por email al correo_operacional del cliente
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.informes import InformeGuardado
from app.models.usuarios import Usuario

router = APIRouter(prefix="/informes", tags=["informes"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class InformeUpsertIn(BaseModel):
    tipo: str                              # "op" | "fmo" | "port"
    sub_project: str
    periodo_desde: str                     # YYYY-MM-DD
    periodo_hasta: str                     # YYYY-MM-DD
    periodo_display: Optional[str] = None
    proyecto_nombre: Optional[str] = None
    html_content: str
    charts_data: Optional[Any] = None     # JSON del rptChartQueue (puede llegar como string o dict)


class EstadoIn(BaseModel):
    estado: str   # "revisado" | "aprobado"


class ComentarioOut(BaseModel):
    id: str                              # uuid4 generado al crear
    autor_email: str
    autor_nombre: Optional[str] = None
    mensaje: str
    created_at: str                      # ISO-8601
    resuelto: bool = False
    resuelto_en: Optional[str] = None
    resuelto_por_email: Optional[str] = None
    resuelto_por_nombre: Optional[str] = None
    respuesta: Optional[str] = None      # texto opcional del autor al subsanar


class InformeOut(BaseModel):
    id: int
    tipo: str
    sub_project: str
    periodo_desde: str
    periodo_hasta: str
    periodo_display: Optional[str]
    proyecto_nombre: Optional[str]
    estado: str
    creado_por_nombre: Optional[str]
    editado_por_nombre: Optional[str]
    aprobado_por_nombre: Optional[str]
    enviado_por_nombre: Optional[str] = None
    creado_en: datetime
    editado_en: Optional[datetime]
    aprobado_en: Optional[datetime]
    correo_enviado: bool
    correo_enviado_en: Optional[datetime]
    comentarios: list[ComentarioOut] = []

    class Config:
        from_attributes = True


class InformeDetailOut(InformeOut):
    html_content: str
    charts_data: Optional[Any] = None


class ComentarioCreateIn(BaseModel):
    mensaje: str


class ComentarioResolverIn(BaseModel):
    respuesta: Optional[str] = None


# Emails con permisos especiales (configurables por env si fuera necesario).
EMAIL_VERIFICADOR = "juan.jose@unergy.io"   # único que puede aprobar/verificar informes
EMAIL_REMITENTE = "laura.h@unergy.io"       # única que puede disparar el envío por email
# Admins también pueden todo
def _es_verificador(u: Usuario) -> bool:
    return (u.email or "").lower() in {EMAIL_VERIFICADOR, "juanjose@unergy.io"} or (u.rol or "") == "admin"

def _es_remitente(u: Usuario) -> bool:
    if _es_verificador(u):
        return True  # el verificador puede enviar también (no se queda atascado el flujo)
    return (u.email or "").lower() == EMAIL_REMITENTE


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_correo_operacional(db: Session, sub_project: str) -> Optional[str]:
    """Busca el correo_operacional del cliente asociado al proyecto."""
    row = db.execute(
        text("""
            SELECT c.correo_operacional
            FROM proyectos p
            JOIN clientes c ON c.id = p.cliente_id
            WHERE p.sub_project = :sp
               OR p.nombre_comercial = :sp
               OR p.alias_monitoreo ILIKE :sp_like
            LIMIT 1
        """),
        {"sp": sub_project, "sp_like": f"%{sub_project}%"},
    ).fetchone()
    if row and row[0]:
        return row[0]
    return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=InformeDetailOut, summary="Crear o actualizar informe guardado")
def upsert_informe(
    payload: InformeUpsertIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Upsert por (tipo, sub_project, periodo_desde, periodo_hasta)."""
    existing = (
        db.query(InformeGuardado)
        .filter_by(
            tipo=payload.tipo,
            sub_project=payload.sub_project,
            periodo_desde=payload.periodo_desde,
            periodo_hasta=payload.periodo_hasta,
        )
        .first()
    )

    now = datetime.now(timezone.utc)

    # Normalizar charts_data: si llega como string JSON, parsearlo a dict para JSONB
    charts_data_parsed = payload.charts_data
    if isinstance(charts_data_parsed, str):
        try:
            charts_data_parsed = json.loads(charts_data_parsed)
        except (ValueError, TypeError):
            charts_data_parsed = None

    if existing:
        # Solo "borrador" se puede sobrescribir.
        # "revisado" y "aprobado" están bloqueados para no perder avances del flujo editorial.
        if existing.estado == "aprobado":
            raise HTTPException(400, "No se puede editar un informe ya aprobado")
        if existing.estado == "revisado":
            raise HTTPException(
                409,
                "Este informe ya está en estado 'revisado'. "
                "Reviértelo a borrador antes de guardar una nueva versión.",
            )
        existing.html_content = payload.html_content
        existing.charts_data = charts_data_parsed
        if payload.proyecto_nombre:
            existing.proyecto_nombre = payload.proyecto_nombre
        if payload.periodo_display:
            existing.periodo_display = payload.periodo_display
        existing.editado_por_id = current_user.id
        existing.editado_por_nombre = current_user.nombre
        existing.editado_en = now
        db.commit()
        db.refresh(existing)
        return existing
    else:
        nuevo = InformeGuardado(
            tipo=payload.tipo,
            sub_project=payload.sub_project,
            periodo_desde=payload.periodo_desde,
            periodo_hasta=payload.periodo_hasta,
            periodo_display=payload.periodo_display,
            proyecto_nombre=payload.proyecto_nombre,
            html_content=payload.html_content,
            charts_data=charts_data_parsed,
            estado="borrador",
            creado_por_id=current_user.id,
            creado_por_nombre=current_user.nombre,
            editado_por_id=current_user.id,
            editado_por_nombre=current_user.nombre,
            editado_en=now,
        )
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return nuevo


@router.get("/envios", summary="Email send history")
def list_envios(
    tipo: Optional[str] = Query(None, description="Filter by email type (otp, informe, alarma)"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """List email send history from email_envios table."""
    params: dict = {"limit": limit}
    where_clauses = []
    if tipo:
        where_clauses.append("tipo = :tipo")
        params["tipo"] = tipo
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = db.execute(
        text(f"""
            SELECT id, destinatario, cc, asunto, tipo, exitoso, error, enviado_at
            FROM email_envios
            {where_sql}
            ORDER BY enviado_at DESC
            LIMIT :limit
        """),
        params,
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/", response_model=list[InformeOut], summary="Listar informes guardados")
def list_informes(
    tipo: Optional[str] = Query(None),
    sub_project: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    periodo_desde_gte: Optional[str] = Query(None, description="Filtrar periodo_desde >= YYYY-MM-DD"),
    periodo_desde_lte: Optional[str] = Query(None, description="Filtrar periodo_desde <= YYYY-MM-DD"),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    q = db.query(InformeGuardado)
    if tipo:
        q = q.filter(InformeGuardado.tipo == tipo)
    if sub_project:
        q = q.filter(InformeGuardado.sub_project == sub_project)
    if estado:
        q = q.filter(InformeGuardado.estado == estado)
    if periodo_desde_gte:
        q = q.filter(InformeGuardado.periodo_desde >= periodo_desde_gte)
    if periodo_desde_lte:
        q = q.filter(InformeGuardado.periodo_desde <= periodo_desde_lte)
    return q.order_by(InformeGuardado.editado_en.desc().nullslast()).limit(limit).all()


@router.get("/{informe_id}", response_model=InformeDetailOut, summary="Detalle de informe")
def get_informe(
    informe_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    return inf


@router.patch("/{informe_id}/estado", response_model=InformeOut, summary="Cambiar estado del informe")
def change_estado(
    informe_id: int,
    payload: EstadoIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")

    allowed = {
        "borrador":  ["revisado"],
        "revisado":  ["aprobado", "borrador"],
        "aprobado":  ["borrador"],   # reabrir — sólo verificador/admin
    }
    if payload.estado not in allowed.get(inf.estado, []):
        raise HTTPException(400, f"Transición inválida: {inf.estado} → {payload.estado}")

    # Sólo el verificador (Juan José) o admin pueden aprobar o reabrir un aprobado.
    if payload.estado == "aprobado" and not _es_verificador(current_user):
        raise HTTPException(
            403,
            "Sólo el verificador autorizado (Juan José) puede aprobar informes."
        )
    if inf.estado == "aprobado" and payload.estado == "borrador" and not _es_verificador(current_user):
        raise HTTPException(
            403,
            "Sólo el verificador autorizado puede reabrir un informe ya aprobado."
        )

    # Si hay comentarios sin resolver, no se puede aprobar.
    if payload.estado == "aprobado":
        coms = inf.comentarios or []
        pendientes = [c for c in coms if not c.get("resuelto")]
        if pendientes:
            raise HTTPException(
                409,
                f"No se puede aprobar: hay {len(pendientes)} comentario(s) sin subsanar."
            )

    now = datetime.now(timezone.utc)
    inf.estado = payload.estado

    if payload.estado == "aprobado":
        inf.aprobado_por_id = current_user.id
        inf.aprobado_por_nombre = current_user.nombre
        inf.aprobado_en = now
    elif payload.estado == "revisado":
        # quien marcó revisado = editor
        inf.editado_por_id = current_user.id
        inf.editado_por_nombre = current_user.nombre
        inf.editado_en = now
    elif payload.estado == "borrador" and inf.estado == "aprobado":
        # reabrir: limpiar campos de aprobación
        inf.aprobado_por_id = None
        inf.aprobado_por_nombre = None
        inf.aprobado_en = None

    db.commit()
    db.refresh(inf)
    return inf


# ── Pipeline de verificación: comentarios ─────────────────────────────────

@router.post("/{informe_id}/comentarios", response_model=InformeDetailOut, summary="Agregar comentario de verificación")
def add_comentario(
    informe_id: int,
    payload: ComentarioCreateIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    import uuid
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    if inf.estado == "aprobado":
        raise HTTPException(409, "El informe ya fue aprobado; no se aceptan más comentarios. Reábrelo antes.")
    if not (payload.mensaje and payload.mensaje.strip()):
        raise HTTPException(400, "El mensaje del comentario no puede estar vacío")

    nuevo = {
        "id": str(uuid.uuid4()),
        "autor_email": current_user.email or "",
        "autor_nombre": current_user.nombre or "",
        "mensaje": payload.mensaje.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resuelto": False,
        "resuelto_en": None,
        "resuelto_por_email": None,
        "resuelto_por_nombre": None,
        "respuesta": None,
    }
    coms = list(inf.comentarios or [])
    coms.append(nuevo)
    inf.comentarios = coms
    # Si estaba en 'revisado', vuelve a borrador hasta que se subsane.
    if inf.estado == "revisado":
        inf.estado = "borrador"
    db.commit()
    db.refresh(inf)
    return inf


@router.patch("/{informe_id}/comentarios/{comentario_id}/resolver",
              response_model=InformeDetailOut, summary="Marcar comentario como subsanado")
def resolver_comentario(
    informe_id: int,
    comentario_id: str,
    payload: ComentarioResolverIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    coms = list(inf.comentarios or [])
    target = next((c for c in coms if c.get("id") == comentario_id), None)
    if not target:
        raise HTTPException(404, "Comentario no encontrado")
    if target.get("resuelto"):
        raise HTTPException(409, "Este comentario ya fue marcado como subsanado")
    target["resuelto"] = True
    target["resuelto_en"] = datetime.now(timezone.utc).isoformat()
    target["resuelto_por_email"] = current_user.email or ""
    target["resuelto_por_nombre"] = current_user.nombre or ""
    if payload.respuesta and payload.respuesta.strip():
        target["respuesta"] = payload.respuesta.strip()
    inf.comentarios = coms
    # Si todos los comentarios quedaron subsanados y estaba en borrador, lo movemos a revisado.
    if all(c.get("resuelto") for c in coms) and inf.estado == "borrador":
        inf.estado = "revisado"
        inf.editado_por_id = current_user.id
        inf.editado_por_nombre = current_user.nombre
        inf.editado_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(inf)
    return inf


@router.delete("/{informe_id}/comentarios/{comentario_id}",
               response_model=InformeDetailOut, summary="Eliminar comentario (sólo el autor o admin)")
def borrar_comentario(
    informe_id: int,
    comentario_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    coms = list(inf.comentarios or [])
    target = next((c for c in coms if c.get("id") == comentario_id), None)
    if not target:
        raise HTTPException(404, "Comentario no encontrado")
    if target.get("autor_email", "").lower() != (current_user.email or "").lower() and (current_user.rol or "") != "admin":
        raise HTTPException(403, "Sólo el autor del comentario (o admin) puede eliminarlo")
    inf.comentarios = [c for c in coms if c.get("id") != comentario_id]
    db.commit()
    db.refresh(inf)
    return inf


@router.delete("/{informe_id}", status_code=204, summary="Eliminar informe guardado")
def delete_informe(
    informe_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    if inf.estado == "aprobado":
        raise HTTPException(400, "No se puede eliminar un informe aprobado")
    db.delete(inf)
    db.commit()


@router.post("/{informe_id}/enviar", summary="Enviar informe aprobado por email")
def enviar_informe(
    informe_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    inf = db.get(InformeGuardado, informe_id)
    if not inf:
        raise HTTPException(404, "Informe no encontrado")
    if inf.estado != "aprobado":
        raise HTTPException(400, "Solo se pueden enviar informes aprobados (verificados)")
    if not _es_remitente(current_user):
        raise HTTPException(
            403,
            "Sólo Laura H. (o el verificador/admin) puede disparar el envío del informe por correo."
        )

    correo = _get_correo_operacional(db, inf.sub_project)
    if not correo:
        raise HTTPException(
            422,
            "No se encontró correo_operacional para este proyecto. "
            "Configúralo en la ficha del cliente.",
        )

    try:
        from app.services.email_service import send_informe_email
        send_informe_email(
            to_email=correo,
            proyecto_nombre=inf.proyecto_nombre or inf.sub_project,
            periodo_display=inf.periodo_display or f"{inf.periodo_desde} — {inf.periodo_hasta}",
            aprobado_por=inf.aprobado_por_nombre or current_user.nombre,
            html_content=inf.html_content,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Error al enviar email: {exc}") from exc

    inf.correo_enviado = True
    inf.correo_enviado_en = datetime.now(timezone.utc)
    inf.enviado_por_id = current_user.id
    inf.enviado_por_nombre = current_user.nombre
    db.commit()
    return {"ok": True, "enviado_a": correo}
