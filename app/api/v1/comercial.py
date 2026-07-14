"""CRM comercial: pipeline Prospección→Oferta→Negociación→Fin.

Capa PREVIA a operación — reutiliza Cliente/Proyecto/Contactos/Documentos
existentes. Solo roles admin y comercial (lectura y escritura).
"""
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.api.v1.clientes import buscar_cliente_duplicado
from app.utils.nombre_matching import mejor_candidato
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.operadores_red import OperadorRed
from app.models.comercial import (
    Oportunidad, OportunidadEstadoHistorial, OportunidadGestion, OportunidadOferta,
)
from app.schemas.comercial import (
    OportunidadCreate, OportunidadUpdate, EstadoChangeIn, GestionCreate, ProyectoDesdeCRMIn,
    OfertaCreate, OfertaUpdate,
)
from app.services.comercial import calcular_alerta, col_now

router = APIRouter(prefix="/comercial", tags=["comercial"])


def _check_comercial(current: Usuario):
    if current.rol.value not in ("admin", "comercial"):
        raise HTTPException(403, "Requiere rol comercial o admin")


def _get_oportunidad_or_404(id: int, db: Session) -> Oportunidad:
    op = (
        db.query(Oportunidad)
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    return op


def _proyecto_out(p: Proyecto) -> dict:
    return {
        "id": p.id,
        "nombre_comercial": p.nombre_comercial,
        "potencia_instalada_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
        "departamento": p.departamento,
        "municipio": p.municipio,
        "operador_red": p.operador_red,
        "operador_red_id": p.operador_red_id,
        "estado": p.estado if isinstance(p.estado, str) else p.estado.value,
        "fecha_estimada_energizacion": p.fecha_estimada_energizacion,
        "fecha_inicio_comercializacion": p.fecha_inicio_comercializacion,
        "mwh_mes_estimado": float(p.mwh_mes_estimado) if p.mwh_mes_estimado is not None else None,
    }


def _oferta_out(o: OportunidadOferta) -> dict:
    return {
        "id": o.id, "oportunidad_id": o.oportunidad_id,
        "tipo": o.tipo if isinstance(o.tipo, str) else o.tipo.value,
        "planta_nombre": o.planta_nombre, "proyecto_id": o.proyecto_id,
        "numero_oferta": o.numero_oferta, "precio_detalle": o.precio_detalle,
        "resultado": o.resultado if isinstance(o.resultado, str) else o.resultado.value,
        "etapa_texto": o.etapa_texto, "fecha_oferta": o.fecha_oferta,
        "fecha_tentativa_inicio": o.fecha_tentativa_inicio,
        "contrato_firmado": o.contrato_firmado, "detalle": o.detalle, "notas": o.notas,
    }


def _resumen_ofertas(ofertas) -> dict:
    """Conteo de ofertas por tipo, p.ej. {'servicios_operacionales': 3, 'compra_energia': 1}."""
    out: dict = {}
    for o in ofertas:
        t = o.tipo if isinstance(o.tipo, str) else o.tipo.value
        out[t] = out.get(t, 0) + 1
    return out


def _op_base_out(op: Oportunidad, cliente: Cliente, ultima_gestion, ahora: datetime) -> dict:
    estado = op.estado if isinstance(op.estado, str) else op.estado.value
    dias, alerta = calcular_alerta(estado, op.estado_desde, ultima_gestion,
                                   settings.COMERCIAL_ALERTA_DIAS, ahora)
    return {
        "id": op.id,
        "nombre": op.nombre or cliente.razon_social_nombre,
        "cliente_id": op.cliente_id,
        "cliente_razon_social": cliente.razon_social_nombre,
        "cliente_nit": cliente.nit_cedula,
        "tipo_servicio": op.tipo_servicio if isinstance(op.tipo_servicio, (str, type(None))) else op.tipo_servicio.value,
        "estado": estado,
        "estado_desde": op.estado_desde,
        "numero_oferta": op.numero_oferta,
        "es_migrada": op.es_migrada,
        "dias_sin_respuesta": dias,
        "alerta": alerta,
        "ultima_gestion_fecha": ultima_gestion,
    }


@router.get("/config")
def get_config(_=Depends(get_current_user)):
    return {"alerta_dias": settings.COMERCIAL_ALERTA_DIAS}


@router.get("/oportunidades")
def list_oportunidades(
    estado: str | None = Query(None),
    tipo_servicio: str | None = Query(None),
    cliente_id: int | None = Query(None),
    q: str | None = Query(None),
    solo_alerta: bool = Query(False),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    ult_sq = (
        db.query(OportunidadGestion.oportunidad_id.label("oid"),
                 func.max(OportunidadGestion.fecha).label("ultima"))
        .group_by(OportunidadGestion.oportunidad_id).subquery()
    )
    proy_sq = (
        db.query(Proyecto.oportunidad_id.label("oid"),
                 func.count(Proyecto.id).label("n"),
                 func.coalesce(func.sum(Proyecto.potencia_instalada_kwp), 0).label("kwp"))
        .filter(Proyecto.deleted_at.is_(None), Proyecto.oportunidad_id.isnot(None))
        .group_by(Proyecto.oportunidad_id).subquery()
    )
    qy = (
        db.query(Oportunidad, Cliente, ult_sq.c.ultima, proy_sq.c.n, proy_sq.c.kwp)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id)
        .outerjoin(ult_sq, ult_sq.c.oid == Oportunidad.id)
        .outerjoin(proy_sq, proy_sq.c.oid == Oportunidad.id)
        .filter(Oportunidad.deleted_at.is_(None), Cliente.deleted_at.is_(None))
    )
    if estado:
        qy = qy.filter(Oportunidad.estado == estado)
    if tipo_servicio:
        # Nuevo: filtra oportunidades que tengan ≥1 sub-oferta de ese tipo.
        con_oferta = db.query(OportunidadOferta.oportunidad_id).filter(
            OportunidadOferta.tipo == tipo_servicio).subquery()
        qy = qy.filter(Oportunidad.id.in_(db.query(con_oferta.c.oportunidad_id)))
    if cliente_id:
        qy = qy.filter(Oportunidad.cliente_id == cliente_id)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(
            Oportunidad.nombre.ilike(like) | Cliente.razon_social_nombre.ilike(like)
        )
    ahora = col_now()
    filas = qy.order_by(Oportunidad.updated_at.desc()).all()
    # Conteo de ofertas por (oportunidad, tipo) en una sola consulta.
    op_ids = [op.id for op, *_ in filas]
    resumen_por_op: dict = {}
    if op_ids:
        cont = (
            db.query(OportunidadOferta.oportunidad_id, OportunidadOferta.tipo,
                     func.count(OportunidadOferta.id))
            .filter(OportunidadOferta.oportunidad_id.in_(op_ids))
            .group_by(OportunidadOferta.oportunidad_id, OportunidadOferta.tipo).all()
        )
        for oid, tipo, n in cont:
            t = tipo if isinstance(tipo, str) else tipo.value
            resumen_por_op.setdefault(oid, {})[t] = int(n)
    out = []
    for op, cli, ultima, n_proy, kwp in filas:
        row = _op_base_out(op, cli, ultima, ahora)
        row["num_proyectos"] = int(n_proy or 0)
        row["capacidad_total_kwp"] = float(kwp or 0)
        row["resumen_ofertas"] = resumen_por_op.get(op.id, {})
        if solo_alerta and not row["alerta"]:
            continue
        out.append(row)
    return out


@router.post("/oportunidades", status_code=201)
def create_oportunidad(
    data: OportunidadCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    if data.cliente_id:
        cliente = (
            db.query(Cliente)
            .filter(Cliente.id == data.cliente_id, Cliente.deleted_at.is_(None))
            .first()
        )
        if not cliente:
            raise HTTPException(422, "Cliente no encontrado")
    else:
        cn = data.cliente_nuevo
        if not data.forzar_cliente_duplicado:
            duplicado = buscar_cliente_duplicado(db, cn.razon_social_nombre)
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
        cliente = Cliente(
            razon_social_nombre=cn.razon_social_nombre,
            nit_cedula=cn.nit_cedula or None,
            origen_tipo=cn.origen_tipo,
            origen_detalle=cn.origen_detalle,
        )
        db.add(cliente)
        db.flush()  # asigna cliente.id sin cerrar la transacción
        for c in cn.contactos:
            db.add(Contacto(cliente_id=cliente.id, nombre=c.nombre,
                            telefono=c.telefono, email=c.email, tipo=c.tipo))

    op = Oportunidad(
        cliente_id=cliente.id,
        nombre=data.nombre,
        tipo_servicio=data.tipo_servicio,
        notas=data.notas,
        estado="prospeccion",          # SIEMPRE server-side (spec §3.1)
        estado_desde=col_now(),
        creado_por_usuario_id=current.id,
    )
    db.add(op)
    db.flush()
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=op.id, estado_anterior=None,
        estado_nuevo="prospeccion", usuario_id=current.id))
    db.commit()
    db.refresh(op)
    return _op_base_out(op, cliente, None, col_now()) | {"num_proyectos": 0, "capacidad_total_kwp": 0.0}


@router.get("/oportunidades/{id}")
def get_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    op = (
        db.query(Oportunidad)
        .options(
            selectinload(Oportunidad.cliente).selectinload(Cliente.contactos),
            selectinload(Oportunidad.proyectos),
            selectinload(Oportunidad.gestiones),
            selectinload(Oportunidad.historial),
            selectinload(Oportunidad.documentos),
            selectinload(Oportunidad.ofertas),
        )
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    ultima = op.gestiones[0].fecha if op.gestiones else None
    base = _op_base_out(op, op.cliente, ultima, col_now())
    base.update({
        "notas": op.notas,
        "fecha_tentativa_inicio_representacion": op.fecha_tentativa_inicio_representacion,
        "fecha_tentativa_inicio_compra_energia": op.fecha_tentativa_inicio_compra_energia,
        "fecha_estimada_firma": op.fecha_estimada_firma,
        "cliente": {
            "id": op.cliente.id,
            "razon_social_nombre": op.cliente.razon_social_nombre,
            "nit_cedula": op.cliente.nit_cedula,
            "origen_tipo": op.cliente.origen_tipo,
            "origen_detalle": op.cliente.origen_detalle,
        },
        "proyectos": [_proyecto_out(p) for p in op.proyectos if p.deleted_at is None],
        "documentos": [
            {"id": d.id, "tipo": d.tipo if isinstance(d.tipo, str) else d.tipo.value,
             "nombre": d.nombre, "numero": d.numero,
             "estado": d.estado if isinstance(d.estado, str) else d.estado.value,
             "archivo_url": d.archivo_url, "archivo_nombre": d.archivo_nombre,
             "fecha": d.fecha}
            for d in op.documentos
        ],
        "gestiones": [
            {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
             "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id}
            for g in op.gestiones
        ],
        "historial": [
            {"id": h.id, "estado_anterior": h.estado_anterior,
             "estado_nuevo": h.estado_nuevo, "fecha": h.created_at,
             "usuario_id": h.usuario_id}
            for h in op.historial
        ],
        "ofertas": [_oferta_out(o) for o in op.ofertas],
        "resumen_ofertas": _resumen_ofertas(op.ofertas),
    })
    return base


@router.patch("/oportunidades/{id}")
def update_oportunidad(
    id: int, data: OportunidadUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(op, k, v)
    db.commit()
    return {"ok": True, "id": op.id}


@router.delete("/oportunidades/{id}", status_code=204)
def delete_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin puede eliminar oportunidades")
    op = _get_oportunidad_or_404(id, db)
    # Los proyectos NO se borran: se desvinculan (spec §7).
    db.query(Proyecto).filter(Proyecto.oportunidad_id == id).update({"oportunidad_id": None})
    op.deleted_at = col_now()
    db.commit()


@router.post("/oportunidades/{id}/estado")
def cambiar_estado(
    id: int, data: EstadoChangeIn,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    actual = op.estado if isinstance(op.estado, str) else op.estado.value
    if data.estado == actual:
        raise HTTPException(409, f"La oportunidad ya está en '{actual}'")
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=op.id, estado_anterior=actual,
        estado_nuevo=data.estado, usuario_id=current.id))
    op.estado = data.estado
    op.estado_desde = col_now()
    db.commit()
    return {"ok": True, "estado": data.estado, "estado_desde": op.estado_desde}


@router.get("/oportunidades/{id}/gestiones")
def list_gestiones(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    gs = (
        db.query(OportunidadGestion)
        .filter(OportunidadGestion.oportunidad_id == id)
        .order_by(OportunidadGestion.fecha.desc())
        .all()
    )
    return [
        {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
         "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id}
        for g in gs
    ]


@router.post("/oportunidades/{id}/gestiones", status_code=201)
def add_gestion(
    id: int, data: GestionCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    g = OportunidadGestion(
        oportunidad_id=id, tipo=data.tipo, descripcion=data.descripcion,
        fecha=data.fecha or col_now(), usuario_id=current.id)
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "tipo": data.tipo, "descripcion": g.descripcion, "fecha": g.fecha}


@router.post("/oportunidades/{id}/proyectos", status_code=201)
def add_proyecto(
    id: int, data: ProyectoDesdeCRMIn,
    forzar: bool = Query(False, description="true: crear aunque exista un nombre muy parecido"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Agregar proyecto desde el CRM. El proyecto creado ES un Proyecto normal
    de la plataforma (misma tabla); solo queda vinculado a la oportunidad.
    Validación bloqueante: operador de red obligatorio y del catálogo."""
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    operador = db.query(OperadorRed).filter(OperadorRed.id == data.operador_red_id).first()
    if not operador:
        raise HTTPException(422, "Debes seleccionar un operador de red válido del catálogo")

    # Mismo aviso de duplicado por nombre que el POST /proyectos general.
    from app.api.v1.proyectos import _buscar_duplicado_por_nombre
    if not forzar:
        duplicado = _buscar_duplicado_por_nombre(db, data.nombre_comercial)
        if duplicado:
            raise HTTPException(409, {
                "codigo": "posible_duplicado",
                "mensaje": f"Ya existe un proyecto con nombre parecido: {duplicado.nombre_comercial}",
                "proyecto_id": duplicado.id,
            })

    p = Proyecto(
        nombre_comercial=data.nombre_comercial,
        potencia_instalada_kwp=data.potencia_instalada_kwp,
        departamento=data.departamento,
        municipio=data.municipio,
        operador_red_id=operador.id,
        # Sincroniza el texto legacy para que las vistas viejas lo muestren.
        operador_red=operador.nombre_comercial or operador.nombre_legal,
        oportunidad_id=id,
        origen="manual",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proyecto_out(p)


@router.get("/oportunidades/{id}/ofertas")
def list_ofertas(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    ofs = (
        db.query(OportunidadOferta)
        .filter(OportunidadOferta.oportunidad_id == id)
        .order_by(OportunidadOferta.id).all()
    )
    return [_oferta_out(o) for o in ofs]


@router.post("/oportunidades/{id}/ofertas", status_code=201)
def create_oferta(
    id: int, data: OfertaCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    o = OportunidadOferta(oportunidad_id=id, **data.model_dump())
    db.add(o)
    db.commit()
    db.refresh(o)
    return _oferta_out(o)


@router.patch("/ofertas/{oferta_id}")
def update_oferta(
    oferta_id: int, data: OfertaUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if not o:
        raise HTTPException(404, "Oferta no encontrada")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    db.commit()
    return {"ok": True, "id": o.id}


@router.delete("/ofertas/{oferta_id}", status_code=204)
def delete_oferta(oferta_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if o:
        db.delete(o)
        db.commit()


@router.post("/backfill")
def backfill(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Migración inicial: 1 oportunidad en 'fin' por cliente existente sin
    oportunidad, vinculando sus proyectos (vía ProyectoInversionista — la
    misma relación que usa GET /clientes/{id}/proyectos). Idempotente."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")

    con_oportunidad = {
        cid for (cid,) in db.query(Oportunidad.cliente_id)
        .filter(Oportunidad.deleted_at.is_(None)).distinct().all()
    }
    clientes = (
        db.query(Cliente).filter(Cliente.deleted_at.is_(None))
        .order_by(Cliente.id).all()
    )
    a_migrar = [c for c in clientes if c.id not in con_oportunidad]

    resumen = {"clientes_a_migrar": len(a_migrar), "proyectos_a_vincular": 0, "detalle": []}
    ahora = col_now()
    for c in a_migrar:
        proyecto_ids = [
            pid for (pid,) in (
                db.query(ProyectoInversionista.proyecto_id)
                .join(Proyecto, Proyecto.id == ProyectoInversionista.proyecto_id)
                .filter(ProyectoInversionista.cliente_id == c.id,
                        Proyecto.deleted_at.is_(None),
                        Proyecto.oportunidad_id.is_(None))
                .distinct().all()
            )
        ]
        resumen["proyectos_a_vincular"] += len(proyecto_ids)
        resumen["detalle"].append({"cliente_id": c.id, "razon_social": c.razon_social_nombre,
                                   "proyectos": len(proyecto_ids)})
        if not dry_run:
            op = Oportunidad(cliente_id=c.id, estado="servicio_operativo", estado_desde=ahora,
                             es_migrada=True, creado_por_usuario_id=current.id)
            db.add(op)
            db.flush()
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=op.id, estado_anterior=None,
                estado_nuevo="servicio_operativo", usuario_id=current.id))
            if proyecto_ids:
                db.query(Proyecto).filter(Proyecto.id.in_(proyecto_ids)).update(
                    {"oportunidad_id": op.id}, synchronize_session=False)
    if not dry_run:
        db.commit()
    resumen["dry_run"] = dry_run
    return resumen


# ── Importación de las hojas de prospección (Google Sheets → CRM) ──────────────
_SEED_PATH = Path("data/comercial_seed.json")

_ETAPA_A_RESULTADO = {
    "aprobado": "aceptado",
    "denegado": "declinado",
    "propuesta enviada": "pendiente",
    "sin respuesta": "pendiente",
}


def _norm_nombre(s: str | None) -> str:
    """Normaliza razón social / nombre de planta para matching: sin tildes,
    minúsculas, sin sufijos societarios, solo alfanumérico."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(s\.?a\.?s\.?|e\.?s\.?p\.?|s\.?a\.?|bic|ltda)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _parse_fecha(s):
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _etapa_global(resultados: set[str]) -> str:
    if "aceptado" in resultados:
        return "servicio_operativo"
    if resultados & {"pendiente"}:
        return "oferta"
    return "prospeccion"


def _build_detalle(row: dict) -> dict | None:
    """Detalle crudo de la hoja para la sub-oferta. Para servicios_operacionales
    parsea 'Servicios buscados' (viñetas) en una lista para identificar cada
    servicio; agrega FPO y, si vinieran, tiempo/tipo de contrato de energía."""
    d: dict = {}
    sb = row.get("servicios_buscados")
    if sb:
        servicios = [s.strip(" •").strip() for s in str(sb).split("•") if s.strip(" •").strip()]
        if servicios:
            d["servicios"] = servicios
        d["servicios_texto"] = sb
    for k in ("fpo", "tiempo", "tipo_contrato"):
        if row.get(k):
            d[k] = row[k]
    return d or None


@router.post("/importar-hojas")
def importar_hojas(
    dry_run: bool = Query(True),
    crear_faltantes: bool = Query(True, description="false: solo enriquece ofertas ya existentes, no crea nuevas"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Carga/sincroniza las hojas de prospección (Servicios Operacionales +
    Comercialización de Energía + Comunidades) al CRM. Una oportunidad por
    cliente (find-or-create); cada fila de hoja = una sub-oferta. Upsert por
    `numero_oferta` o, si falta, por (cliente, tipo, planta): si la oferta ya
    existe, RELLENA los campos vacíos (detalle/precio/contrato/planta/fecha) sin
    pisar `resultado`/`etapa`. `crear_faltantes=false` solo enriquece. Solo
    admin; `dry_run=true` no escribe."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")
    if not _SEED_PATH.exists():
        raise HTTPException(500, f"No se encontró la semilla en {_SEED_PATH}")
    seed = json.loads(_SEED_PATH.read_text(encoding="utf-8"))

    # Índices para matching.
    proy_idx = {}
    for pid, nom in db.query(Proyecto.id, Proyecto.nombre_comercial).filter(Proyecto.deleted_at.is_(None)).all():
        if nom:
            proy_idx.setdefault(_norm_nombre(nom), pid)

    # planta→empresa dueña (para cruzar la hoja de energía, cuya 'empresa' a veces
    # es el nombre de la planta) usando las filas de servicios como referencia.
    planta_a_empresa = {}
    for row in seed:
        if row.get("planta_nombre"):
            planta_a_empresa[_norm_nombre(row["planta_nombre"])] = row["empresa"]

    cli_idx = {}
    for c in db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all():
        cli_idx.setdefault(_norm_nombre(c.razon_social_nombre), c)

    op_por_cliente = {}
    for op in db.query(Oportunidad).filter(Oportunidad.deleted_at.is_(None)).all():
        op_por_cliente.setdefault(op.cliente_id, op)

    def _client_key(empresa_raw: str) -> str:
        """Clave normalizada del cliente DUEÑO de la fila: resuelve el caso de la
        hoja de energía donde 'empresa' es en realidad el nombre de una planta."""
        key = _norm_nombre(empresa_raw)
        if key in cli_idx:
            return key
        dueno = planta_a_empresa.get(key)
        if dueno:
            return _norm_nombre(dueno)
        return key

    # Clave de dedup/upsert: por numero_oferta si existe; si no, (cliente, tipo, planta).
    of_por_key = {}
    existentes = (
        db.query(OportunidadOferta, Cliente.razon_social_nombre)
        .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id).all()
    )
    for o, razon in existentes:
        t = o.tipo if isinstance(o.tipo, str) else o.tipo.value
        k = o.numero_oferta if o.numero_oferta else (_norm_nombre(razon), t, _norm_nombre(o.planta_nombre))
        of_por_key.setdefault(k, o)
    seen_run = set()   # dedup dentro del propio seed

    res = {
        "dry_run": dry_run,
        "clientes": {"a_crear": 0, "reusados": 0},
        "ofertas": {"creadas": 0, "enriquecidas": 0, "sin_cambio": 0, "faltantes_no_creadas": 0},
        "sin_empresa": 0,
        "detalle": {"clientes_nuevos": [], "sin_match_planta": [], "fusionados_por_similitud": []},
    }
    ahora = col_now()
    # Acumula resultados por cliente para derivar la etapa global de la oportunidad.
    resultados_por_cli: dict = {}
    # Oportunidades creadas en ESTE import (solo a estas se les fija la etapa global;
    # las preexistentes conservan su estado).
    ops_creadas: set = set()

    def cliente_para(empresa_raw):
        key = _norm_nombre(empresa_raw)
        if key in cli_idx:
            res["clientes"]["reusados"] += 1
            return cli_idx[key]
        dueno = planta_a_empresa.get(key)
        if dueno and _norm_nombre(dueno) in cli_idx:
            res["clientes"]["reusados"] += 1
            return cli_idx[_norm_nombre(dueno)]
        # Sin match exacto -- antes de crear uno nuevo, intenta un match difuso
        # (mismo algoritmo de proyectos/clientes manuales, ver nombre_matching.py).
        # Import automático sin humano presente: si el match es de baja confianza
        # o ambiguo, mejor_candidato() ya devuelve None y se sigue creando como
        # antes -- esto solo evita el caso confiable (p. ej. "Quantum" vs "Quantum
        # Energy Ingenieria S.A.S.", el caso real que motivó este cambio).
        candidatos = [(c, [c.razon_social_nombre]) for c in cli_idx.values()]
        match, score = mejor_candidato(empresa_raw, candidatos)
        if match:
            res["clientes"]["reusados"] += 1
            res["detalle"]["fusionados_por_similitud"].append({
                "empresa_hoja": empresa_raw,
                "cliente_existente": match.razon_social_nombre,
                "score": score,
            })
            cli_idx[key] = match
            return match
        res["clientes"]["a_crear"] += 1
        res["detalle"]["clientes_nuevos"].append(empresa_raw)
        if dry_run:
            return None
        c = Cliente(razon_social_nombre=empresa_raw)
        db.add(c)
        db.flush()
        cli_idx[key] = c
        return c

    def oportunidad_para(cliente):
        if cliente is None:
            return None
        op = op_por_cliente.get(cliente.id)
        if op:
            return op
        op = Oportunidad(cliente_id=cliente.id, estado="prospeccion",
                         estado_desde=ahora, es_migrada=True,
                         creado_por_usuario_id=current.id)
        db.add(op)
        db.flush()
        db.add(OportunidadEstadoHistorial(
            oportunidad_id=op.id, estado_anterior=None,
            estado_nuevo="prospeccion", usuario_id=current.id))
        op_por_cliente[cliente.id] = op
        ops_creadas.add(op.id)
        return op

    for row in seed:
        empresa = (row.get("empresa") or "").strip()
        if not empresa:
            res["sin_empresa"] += 1
            continue
        tipo = row["tipo"]
        num = row.get("numero_oferta")
        planta = row.get("planta_nombre") or (empresa if tipo == "compra_energia" else None)
        key = num if num else (_client_key(empresa), tipo, _norm_nombre(planta))
        etapa = (row.get("etapa_texto") or "").strip().lower()
        resultado = _ETAPA_A_RESULTADO.get(etapa, "pendiente")
        proj_id = proy_idx.get(_norm_nombre(planta)) if planta else None
        if planta and proj_id is None:
            res["detalle"]["sin_match_planta"].append(planta)
        detalle = _build_detalle(row)

        existente = of_por_key.get(key)
        if existente is not None:
            # Enriquecer: rellenar SOLO los campos vacíos; nunca pisar resultado/etapa.
            if not dry_run:
                campos = {
                    "detalle": detalle, "precio_detalle": row.get("precio_detalle"),
                    "contrato_firmado": row.get("contrato_firmado"), "planta_nombre": planta,
                    "proyecto_id": proj_id, "fecha_oferta": _parse_fecha(row.get("fecha_oferta")),
                }
                cambio = False
                for campo, val in campos.items():
                    if val is not None and getattr(existente, campo) in (None, "", {}):
                        setattr(existente, campo, val)
                        cambio = True
                res["ofertas"]["enriquecidas" if cambio else "sin_cambio"] += 1
            else:
                res["ofertas"]["enriquecidas"] += 1
            continue

        if key in seen_run:      # duplicado dentro del propio seed
            res["ofertas"]["sin_cambio"] += 1
            continue
        seen_run.add(key)

        if not crear_faltantes:
            res["ofertas"]["faltantes_no_creadas"] += 1
            continue

        cliente = cliente_para(empresa)
        if not dry_run and cliente is not None:
            op = oportunidad_para(cliente)
            if op is not None:
                nueva = OportunidadOferta(
                    oportunidad_id=op.id, tipo=tipo, planta_nombre=planta,
                    proyecto_id=proj_id, numero_oferta=num,
                    precio_detalle=row.get("precio_detalle"), resultado=resultado,
                    etapa_texto=row.get("etapa_texto"),
                    contrato_firmado=row.get("contrato_firmado"),
                    fecha_oferta=_parse_fecha(row.get("fecha_oferta")),
                    detalle=detalle)
                db.add(nueva)
                of_por_key[key] = nueva
                resultados_por_cli.setdefault(cliente.id, set()).add(resultado)
        res["ofertas"]["creadas"] += 1

    # Etapa global solo de las oportunidades creadas en este import.
    if not dry_run:
        for cli_id, resultados in resultados_por_cli.items():
            op = op_por_cliente.get(cli_id)
            if op and op.id in ops_creadas:
                op.estado = _etapa_global(resultados)
        db.commit()
    return res


@router.post("/dedup-clientes")
def dedup_clientes(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Limpia los clientes-prospecto que el import creó por duplicado cuando ya
    existía el cliente operativo. CONSERVADOR y REVERSIBLE:
    - candidato = cliente con origen_tipo NULL + oportunidad es_migrada con ≥1
      oferta + SIN huella operativa (no inversionista/contrato/PPA); o sea un
      prospecto puro creado por el import.
    - canónico (alta confianza): (a) la planta de alguna de sus ofertas coincide
      con un Proyecto existente cuyo dueño (inversionista) es un cliente NO
      prospecto → ese dueño; o (b) el nombre normaliza exactamente igual a otro
      cliente no prospecto. Si no hay canónico claro, se deja intacto.
    - acción: mueve las ofertas al canónico (enlazando proyecto_id) y hace
      soft-delete del prospecto y su oportunidad (deleted_at; reversible).
    Idempotente. Solo admin; dry_run=true no escribe."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")
    from app.services.clientes_panel import proyectos_por_cliente

    # Candidatos: clientes con oportunidad es_migrada que tiene ofertas.
    cand_ids = {
        cid for (cid,) in db.query(Oportunidad.cliente_id)
        .join(OportunidadOferta, OportunidadOferta.oportunidad_id == Oportunidad.id)
        .filter(Oportunidad.deleted_at.is_(None), Oportunidad.es_migrada.is_(True))
        .distinct().all()
    }
    footprint = proyectos_por_cliente(db, cand_ids) if cand_ids else {}
    prospect_ids = {
        c.id for c in db.query(Cliente).filter(Cliente.id.in_(cand_ids)).all()
        if c.id in cand_ids and c.origen_tipo is None and c.deleted_at is None
        and not footprint.get(c.id)
    } if cand_ids else set()

    # Índices: Proyecto por nombre normalizado y sus dueños (inversionistas).
    proy_norm = {}
    for pid, nom in db.query(Proyecto.id, Proyecto.nombre_comercial).filter(Proyecto.deleted_at.is_(None)).all():
        if nom:
            proy_norm.setdefault(_norm_nombre(nom), pid)
    owners: dict = {}
    for pid, cid in db.query(ProyectoInversionista.proyecto_id, ProyectoInversionista.cliente_id).all():
        owners.setdefault(pid, []).append(cid)
    # Clientes NO prospecto por nombre normalizado (para match exacto de nombre).
    cli_no_prospecto = {}
    for c in db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all():
        if c.id not in prospect_ids:
            cli_no_prospecto.setdefault(_norm_nombre(c.razon_social_nombre), c.id)

    res = {"dry_run": dry_run, "prospectos": len(prospect_ids),
           "fusionados": 0, "sin_canonico": 0, "detalle": []}

    for C in db.query(Cliente).filter(Cliente.id.in_(prospect_ids)).all() if prospect_ids else []:
        ofertas = (
            db.query(OportunidadOferta)
            .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
            .filter(Oportunidad.cliente_id == C.id, Oportunidad.deleted_at.is_(None)).all()
        )
        # Nombres a probar: razón social + planta de cada oferta.
        nombres = [C.razon_social_nombre] + [o.planta_nombre for o in ofertas if o.planta_nombre]
        canonico = None
        matched_proy = None
        regla = None
        for nombre in nombres:
            k = _norm_nombre(nombre)
            if not k:
                continue
            pid = proy_norm.get(k)
            if pid:
                for owner in owners.get(pid, []):
                    if owner not in prospect_ids and owner != C.id:
                        canonico, matched_proy, regla = owner, pid, "planta→dueño"
                        break
            if canonico:
                break
            did = cli_no_prospecto.get(k)
            if did and did != C.id:
                canonico, regla = did, "nombre exacto"
                break
        if not canonico:
            res["sin_canonico"] += 1
            continue

        res["fusionados"] += 1
        res["detalle"].append({"prospecto_id": C.id, "prospecto": C.razon_social_nombre,
                               "canonico_id": canonico, "regla": regla,
                               "ofertas": len(ofertas), "proyecto": matched_proy})
        if dry_run:
            continue

        # Oportunidad destino del canónico (reusar o crear).
        d_op = (db.query(Oportunidad)
                .filter(Oportunidad.cliente_id == canonico, Oportunidad.deleted_at.is_(None))
                .order_by(Oportunidad.id).first())
        if not d_op:
            d_op = Oportunidad(cliente_id=canonico, estado="servicio_operativo",
                               estado_desde=col_now(), es_migrada=True,
                               creado_por_usuario_id=current.id)
            db.add(d_op)
            db.flush()
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=d_op.id, estado_anterior=None,
                estado_nuevo="servicio_operativo", usuario_id=current.id))
        for o in ofertas:
            o.oportunidad_id = d_op.id
            if matched_proy and o.proyecto_id is None:
                o.proyecto_id = matched_proy
        # Soft-delete del prospecto y sus oportunidades (ya vacías).
        for op in db.query(Oportunidad).filter(Oportunidad.cliente_id == C.id, Oportunidad.deleted_at.is_(None)).all():
            op.deleted_at = col_now()
        C.deleted_at = col_now()

    if not dry_run:
        db.commit()
    return res
