from datetime import date, datetime, timedelta, timezone
import io
import time
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, joinedload, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera, FronteraLectura, FronteraQuoiaIgnorada
from app.models.operadores_red import OperadorRed
from app.models.proyectos import Proyecto
from app.schemas.fronteras import (
    FronteraCreate, FronteraUpdate, FronteraOut,
    FronteraLecturaCreate, FronteraLecturaOut, FronteraResumen,
    FronteraQuoiaPendiente, FronteraQuoiaConfirmar, FronteraQuoiaIgnorar,
)
from app.services.mgs.quoia_client import QuoiaClient
from app.services.mgs.gaia_client import GaiaClient, _mgs_number, get_frt_meter_info
from app.services.contactos import get_contactos, get_clientes_contacto
from app.services.operadores_red_sync import sincronizar_operador_red
from app.utils.nombre_matching import mejor_candidato

router = APIRouter(prefix="/fronteras", tags=["Fronteras"])

_quoia: QuoiaClient | None = None
_gaia: GaiaClient | None = None


def _sync_operador_red_para_proyecto(db: Session, proyecto_id: int | None) -> None:
    """Rellena `operador_red_id` entre este proyecto y sus fronteras (en la
    dirección que haga falta) tras crear/editar una frontera vinculada."""
    if proyecto_id is None:
        return
    proyecto = (
        db.query(Proyecto)
        .options(selectinload(Proyecto.fronteras))
        .filter(Proyecto.id == proyecto_id)
        .first()
    )
    if proyecto is None:
        return
    sincronizar_operador_red(db, proyecto)
    db.commit()


def _get_quoia() -> QuoiaClient:
    global _quoia
    if _quoia is None:
        _quoia = QuoiaClient()
    if not _quoia.enabled:
        raise HTTPException(503, "QUOIA_API_TOKEN not configured")
    return _quoia


def _get_gaia() -> GaiaClient:
    global _gaia
    if _gaia is None:
        _gaia = GaiaClient()
    if not _gaia.enabled:
        raise HTTPException(503, "Credenciales de Gaia/Quoia no configuradas (GAIA_USER/GAIA_PASS)")
    return _gaia


# ── Nodos (medidores) de Quoia vía Gaia/JWT — cacheados 1 h ───────────────────
# El diagrama fasorial se alimenta del snapshot eléctrico del nodo, que se pide
# por node_id. La lista de nodos y su lectura usan GaiaClient (GAIA_USER/PASS),
# que es la credencial realmente configurada en producción.
_nodes_cache: list[dict] = []
_nodes_ts: float = 0.0
_NODES_TTL = 3600.0


def _list_gaia_nodes(gaia: GaiaClient) -> list[dict]:
    """Lista de nodos del retailer (cacheada 1 h). Conserva el cache previo si
    la API responde vacío en vez de invalidarlo."""
    global _nodes_cache, _nodes_ts
    now = time.monotonic()
    if not _nodes_cache or (now - _nodes_ts) >= _NODES_TTL:
        nodes = gaia.get_all_nodes()
        if nodes:
            _nodes_cache = nodes
            _nodes_ts = now
    return _nodes_cache


def _to_out(f: Frontera, db: Session) -> FronteraOut:
    d = FronteraOut.model_validate(f)
    if f.proyecto:
        d.proyecto_nombre = f.proyecto.nombre_comercial
        d.clientes_cgm = [
            {**c, "correos": get_contactos(db, "cgm", cliente_id=c["id"])}
            for c in get_clientes_contacto(db, "cgm", f.proyecto_id)
        ]
    if f.operador:
        d.operador_red_id = f.operador.id
        d.operador_comercial = f.operador.nombre_comercial or f.operador.nombre_legal
        d.operador_correos = [c.email for c in f.operador.contactos]
    return d


_FRONTERA_OPTS = (
    joinedload(Frontera.proyecto),
    joinedload(Frontera.operador).joinedload(OperadorRed.contactos),
)


# ── Resumen (must be before /{id} to avoid route conflict) ────────────────────

@router.get("/resumen", response_model=FronteraResumen)
def fronteras_resumen(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Summary of all fronteras: active count, energy totals, stale meters."""
    # Count active/inactive fronteras (exclude soft-deleted)
    total_activas = (
        db.query(func.count(Frontera.id))
        .filter(Frontera.deleted_at.is_(None))
        .filter(Frontera.estado.in_(["activa", "en_registro"]))
        .scalar() or 0
    )
    total_inactivas = (
        db.query(func.count(Frontera.id))
        .filter(Frontera.deleted_at.is_(None))
        .filter(Frontera.estado.in_(["cancelada", "en_falla"]))
        .scalar() or 0
    )

    # Energy totals last 30 days
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    energy = db.execute(text("""
        SELECT
            COALESCE(SUM(energia_activa_import_kwh), 0) AS total_import,
            COALESCE(SUM(energia_activa_export_kwh), 0) AS total_export
        FROM fronteras_lecturas
        WHERE fecha_hora >= :cutoff
    """), {"cutoff": cutoff_30d}).first()
    total_import = float(energy.total_import) if energy else 0.0
    total_export = float(energy.total_export) if energy else 0.0

    # Fronteras without readings in 7+ days
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    stale_rows = db.execute(text("""
        SELECT f.id, f.nombre_frontera, f.codigo_frontera,
               MAX(fl.fecha_hora) AS ultima_lectura
        FROM fronteras f
        LEFT JOIN fronteras_lecturas fl ON fl.frontera_id = f.id
        WHERE f.deleted_at IS NULL
          AND f.estado = 'activa'
        GROUP BY f.id, f.nombre_frontera, f.codigo_frontera
        HAVING MAX(fl.fecha_hora) IS NULL OR MAX(fl.fecha_hora) < :cutoff
        ORDER BY f.nombre_frontera
    """), {"cutoff": cutoff_7d}).fetchall()

    fronteras_sin_datos = [
        {
            "id": r.id,
            "nombre_frontera": r.nombre_frontera,
            "codigo_frontera": r.codigo_frontera,
            "ultima_lectura": r.ultima_lectura.isoformat() if r.ultima_lectura else None,
        }
        for r in stale_rows
    ]

    return FronteraResumen(
        total_activas=total_activas,
        total_inactivas=total_inactivas,
        total_kwh_import_30d=round(total_import, 2),
        total_kwh_export_30d=round(total_export, 2),
        sin_datos_recientes=len(fronteras_sin_datos),
        fronteras_sin_datos=fronteras_sin_datos,
    )


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[FronteraOut])
def list_fronteras(
    proyecto_id: int | None = Query(None),
    tipo_frontera: str | None = Query(None, description="Filter by tipo_frontera"),
    estado: str | None = Query(None, description="Filter by estado (activa, en_registro, cancelada, en_falla)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        db.query(Frontera)
        .options(*_FRONTERA_OPTS)
        .filter(Frontera.deleted_at.is_(None))
    )
    if proyecto_id:
        q = q.filter(Frontera.proyecto_id == proyecto_id)
    if tipo_frontera:
        q = q.filter(Frontera.tipo_frontera == tipo_frontera)
    if estado:
        q = q.filter(Frontera.estado == estado)
    return [_to_out(f, db) for f in q.order_by(Frontera.codigo_frontera).offset(skip).limit(limit).all()]


# ── Create ────────────────────────────────────────────────────────────────────

def _buscar_duplicado_frontera(
    db: Session, nombre_frontera: str | None, tipo_frontera: str | None = None,
) -> Frontera | None:
    """Busca una frontera existente con nombre parecido, via solapamiento de
    tokens + similitud de texto (mismo algoritmo que _buscar_duplicado_por_nombre
    en proyectos, ver app/utils/nombre_matching.py) -- detecta parecidos aunque
    no sea un caso de "un nombre contenido en el otro" (p. ej. "AGGE Extractora
    Monterrey" vs "AGGE Frontera Monterrey").

    Si se pasa tipo_frontera, solo compara contra fronteras del mismo tipo --
    reduce falsos positivos entre fronteras de naturaleza distinta (generación
    vs consumo) que comparten palabras en el nombre.

    Deliberadamente permisivo -- no bloquea, solo avisa (se puede forzar la
    creación con forzar=true)."""
    if not nombre_frontera:
        return None
    q = db.query(Frontera).filter(Frontera.deleted_at.is_(None))
    if tipo_frontera:
        q = q.filter(Frontera.tipo_frontera == tipo_frontera)
    candidatos = [(f, [f.nombre_frontera]) for f in q.all()]
    item, _score = mejor_candidato(nombre_frontera, candidatos)
    return item


@router.post("", response_model=FronteraOut, status_code=201)
def create_frontera(
    body: FronteraCreate,
    forzar: bool = Query(False, description="true: crear igual aunque exista una frontera con nombre muy parecido"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if body.codigo_frontera:
        existing = db.query(Frontera).filter_by(codigo_frontera=body.codigo_frontera).first()
        if existing:
            for k, v in body.model_dump(exclude_none=True).items():
                setattr(existing, k, v)
            db.commit()
            _sync_operador_red_para_proyecto(db, existing.proyecto_id)
            db.refresh(existing)
            return _to_out(db.query(Frontera).options(*_FRONTERA_OPTS).filter(Frontera.id == existing.id).first(), db)

    if not forzar:
        duplicado = _buscar_duplicado_frontera(db, body.nombre_frontera, body.tipo_frontera)
        if duplicado:
            raise HTTPException(
                409,
                {
                    "mensaje": (
                        f"Ya existe una frontera con un nombre muy parecido: "
                        f"'{duplicado.nombre_frontera}' (ID {duplicado.id})."
                    ),
                    "duplicado_nombre": True,
                    "candidato_id": duplicado.id,
                    "candidato_nombre": duplicado.nombre_frontera,
                },
            )

    obj = Frontera(**body.model_dump())
    db.add(obj)
    db.commit()
    _sync_operador_red_para_proyecto(db, obj.proyecto_id)
    db.refresh(obj)
    return _to_out(db.query(Frontera).options(*_FRONTERA_OPTS).filter(Frontera.id == obj.id).first(), db)


@router.get("/debug-quoia-border")
def debug_quoia_border(frt_code: str = Query(...), _=Depends(get_current_user)):
    """Diagnóstico de solo lectura: ¿este frt_code aparece en el listado de
    fronteras que devuelve Quoia (gaia.get_all_borders(), la misma fuente que
    usa Reporte CGM para el nombre y el ID del border)? Sirve para diagnosticar
    filas sin nombre / "Sin reporte" en el Excel -- pasa exactamente cuando
    este código no aparece en ese listado. Va ANTES de /{frontera_id} en el
    router -- si no, FastAPI intenta parsear "debug-quoia-border" como int."""
    gaia = _get_gaia()
    code = frt_code.strip().lower()
    borders = gaia.get_all_borders()
    match = None
    for b in borders:
        for key in ("frt_generation", "frt_consumption"):
            frt = b.get(key) or {}
            if (frt.get("frt_code") or "").strip().lower() == code:
                match = {"proyecto_quoia": b.get("name"), "tipo": key, **frt}
                break
        if match:
            break
    return {
        "frt_code": code,
        "total_borders_en_quoia": len(borders),
        "encontrado": match is not None,
        "detalle": match,
    }


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{frontera_id}", response_model=FronteraOut)
def get_frontera(
    frontera_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f = (
        db.query(Frontera)
        .options(*_FRONTERA_OPTS)
        .filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None))
        .first()
    )
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    return _to_out(f, db)


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{frontera_id}", response_model=FronteraOut)
def update_frontera(
    frontera_id: int,
    body: FronteraUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f = (
        db.query(Frontera)
        .options(*_FRONTERA_OPTS)
        .filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None))
        .first()
    )
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    db.commit()
    _sync_operador_red_para_proyecto(db, f.proyecto_id)
    db.refresh(f)
    return _to_out(
        db.query(Frontera)
        .options(*_FRONTERA_OPTS)
        .filter(Frontera.id == f.id)
        .first(),
        db,
    )


# ── Soft Delete ───────────────────────────────────────────────────────────────

@router.delete("/{frontera_id}", status_code=204)
def delete_frontera(
    frontera_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f = db.query(Frontera).filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None)).first()
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    f.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ── Lecturas (historical meter readings) ──────────────────────────────────────

@router.get("/{frontera_id}/lecturas", response_model=list[FronteraLecturaOut])
def get_lecturas(
    frontera_id: int,
    desde: date | None = Query(None, description="Start date (inclusive)"),
    hasta: date | None = Query(None, description="End date (inclusive)"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Historical meter readings for a frontera with optional date range filter."""
    # Verify frontera exists
    f = db.query(Frontera).filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None)).first()
    if not f:
        raise HTTPException(404, "Frontera no encontrada")

    q = db.query(FronteraLectura).filter(FronteraLectura.frontera_id == frontera_id)
    if desde:
        q = q.filter(FronteraLectura.fecha_hora >= datetime.combine(desde, datetime.min.time()))
    if hasta:
        q = q.filter(FronteraLectura.fecha_hora <= datetime.combine(hasta, datetime.max.time()))
    return q.order_by(FronteraLectura.fecha_hora.desc()).limit(limit).all()


@router.post("/{frontera_id}/lecturas", response_model=FronteraLecturaOut, status_code=201)
def create_lectura(
    frontera_id: int,
    body: FronteraLecturaCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Create a single meter reading for a frontera."""
    f = db.query(Frontera).filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None)).first()
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    obj = FronteraLectura(frontera_id=frontera_id, **body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{frontera_id}/lecturas/bulk", response_model=list[FronteraLecturaOut], status_code=201)
def create_lecturas_bulk(
    frontera_id: int,
    body: list[FronteraLecturaCreate],
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Create multiple meter readings for a frontera in a single request."""
    f = db.query(Frontera).filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None)).first()
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    if not body:
        raise HTTPException(422, "La lista de lecturas no puede estar vacía")
    objects = [FronteraLectura(frontera_id=frontera_id, **item.model_dump()) for item in body]
    db.add_all(objects)
    db.commit()
    for obj in objects:
        db.refresh(obj)
    return objects


# ── Fronteras pendientes de Quoia (detectar + confirmar, nunca auto-escribir) ──

def _iter_borders_frt(gaia: GaiaClient):
    """Yield (frt_code_lower, categoria, nombre_quoia, frt_meta) para cada
    frt_generation/frt_consumption de cada border de Quoia."""
    for border in gaia.get_all_borders():
        nombre = (border.get("name") or "").strip()
        for key, categoria in (("frt_generation", "generacion"), ("frt_consumption", "consumo")):
            frt = border.get(key)
            if not frt:
                continue
            frt_code = (frt.get("frt_code") or "").strip()
            # Placeholder tipo "N/A" que a veces carga Quoia cuando el border no
            # tiene codigo real todavia -- no es un frt_code utilizable (y la
            # barra rompe la ruta al confirmar, ya que frt_code va en la URL).
            if not frt_code or "/" in frt_code:
                continue
            yield frt_code.lower(), categoria, nombre, frt


@router.get("/quoia/pendientes", response_model=list[FronteraQuoiaPendiente])
def fronteras_quoia_pendientes(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Borders de Quoia que todavia no tienen fila en `fronteras` ni fueron
    marcados como ignorados -- para revisar y confirmar manualmente, nunca
    se crean solos."""
    gaia = _get_gaia()

    existentes = {
        c.lower() for (c,) in db.query(Frontera.codigo_frontera).filter(Frontera.codigo_frontera.isnot(None)).all()
    }
    ignorados = {c.lower() for (c,) in db.query(FronteraQuoiaIgnorada.frt_code).all()}
    proyectos = db.query(Proyecto.id, Proyecto.nombre_comercial).filter(Proyecto.deleted_at.is_(None)).all()

    pendientes: list[FronteraQuoiaPendiente] = []
    vistos: set[str] = set()
    for frt_code, categoria, nombre_quoia, _frt in _iter_borders_frt(gaia):
        if frt_code in existentes or frt_code in ignorados or frt_code in vistos:
            continue
        vistos.add(frt_code)

        sugerido_id, sugerido_nombre = None, None
        num = _mgs_number(nombre_quoia)
        if num is not None:
            for pid, pnombre in proyectos:
                if _mgs_number(pnombre or "") == num:
                    sugerido_id, sugerido_nombre = pid, pnombre
                    break

        pendientes.append(FronteraQuoiaPendiente(
            frt_code=frt_code,
            nombre_quoia=nombre_quoia,
            categoria=categoria,
            proyecto_sugerido_id=sugerido_id,
            proyecto_sugerido_nombre=sugerido_nombre,
        ))
    return pendientes


@router.post("/quoia/pendientes/{frt_code}/confirmar", response_model=FronteraOut, status_code=201)
def confirmar_frontera_quoia(
    frt_code: str,
    body: FronteraQuoiaConfirmar,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Crea la fila real en `fronteras` para un border de Quoia, tras
    confirmacion manual del proyecto al que pertenece."""
    gaia = _get_gaia()

    if not db.query(Proyecto.id).filter(Proyecto.id == body.proyecto_id).first():
        raise HTTPException(404, "Proyecto no encontrado")
    if db.query(Frontera).filter(func.lower(Frontera.codigo_frontera) == frt_code.lower()).first():
        raise HTTPException(409, "Ya existe una frontera con ese codigo_frontera")

    match = None
    for code, categoria, nombre_quoia, frt in _iter_borders_frt(gaia):
        if code == frt_code.lower():
            match = (categoria, nombre_quoia, frt)
            break
    if not match:
        raise HTTPException(404, "Ese frt_code ya no aparece en Quoia")
    categoria, nombre_quoia, frt = match

    info_ppal, info_resp = get_frt_meter_info(gaia, frt_code)

    nombre_base = body.nombre_frontera or nombre_quoia or frt_code
    nombre_default = f"{nombre_base} Consumo" if categoria == "consumo" and not body.nombre_frontera else nombre_base

    fecha_registro_asic = None
    init_date = frt.get("init_date")
    if init_date:
        try:
            fecha_registro_asic = date.fromisoformat(init_date)
        except ValueError:
            pass

    obj = Frontera(
        proyecto_id=body.proyecto_id,
        codigo_frontera=frt_code,
        nombre_frontera=nombre_default,
        codigo_propio=body.codigo_propio,
        tipo_frontera=body.tipo_frontera or ("generacion" if categoria == "generacion" else "consumo_auxiliar"),
        estado="activa",
        quoia_border_id=frt.get("id"),
        fecha_registro_asic=fecha_registro_asic,
    )
    if info_ppal:
        obj.marca_med_ppal = info_ppal.get("marca")
        obj.modelo_med_ppal = info_ppal.get("modelo")
        obj.nro_serie_med_ppal = info_ppal.get("serie")
    if info_resp:
        obj.marca_med_resp = info_resp.get("marca")
        obj.modelo_med_resp = info_resp.get("modelo")
        obj.nro_serie_med_resp = info_resp.get("serie")
    db.add(obj)
    db.commit()
    _sync_operador_red_para_proyecto(db, obj.proyecto_id)
    db.refresh(obj)
    return _to_out(db.query(Frontera).options(*_FRONTERA_OPTS).filter(Frontera.id == obj.id).first(), db)


@router.post("/quoia/pendientes/{frt_code}/ignorar", status_code=204)
def ignorar_frontera_quoia(
    frt_code: str,
    body: FronteraQuoiaIgnorar,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """Marca un border de Quoia como 'no aplica' para que deje de aparecer
    en /quoia/pendientes (ej. medidor de prueba, border de un tercero)."""
    code = frt_code.lower()
    if db.query(FronteraQuoiaIgnorada).filter(FronteraQuoiaIgnorada.frt_code == code).first():
        return
    db.add(FronteraQuoiaIgnorada(frt_code=code, motivo=body.motivo, ignorado_por_usuario_id=usuario.id))
    db.commit()


def _backfill_medidor_info(db: Session, dry_run: bool = True) -> dict:
    """Completa marca/modelo/serie de medidor (ppal + respaldo) desde Quoia en
    fronteras que ya existen pero les falta ese dato. Nunca pisa un campo que
    ya tenga valor -- solo llena huecos."""
    gaia = _get_gaia()
    fronteras = db.query(Frontera).filter(
        Frontera.codigo_frontera.isnot(None),
        or_(
            Frontera.marca_med_ppal.is_(None), Frontera.modelo_med_ppal.is_(None),
            Frontera.nro_serie_med_ppal.is_(None), Frontera.marca_med_resp.is_(None),
            Frontera.modelo_med_resp.is_(None), Frontera.nro_serie_med_resp.is_(None),
        ),
    ).all()

    actualizadas = []
    sin_info = []
    for f in fronteras:
        info_ppal, info_resp = get_frt_meter_info(gaia, f.codigo_frontera)
        cambios = {}
        for prefix, info in (("ppal", info_ppal), ("resp", info_resp)):
            if not info:
                continue
            for campo, valor in (("marca", info.get("marca")), ("modelo", info.get("modelo")), ("serie", info.get("serie"))):
                if not valor:
                    continue
                attr = f"{'nro_serie' if campo == 'serie' else campo}_med_{prefix}"
                if getattr(f, attr) is None:
                    cambios[attr] = valor

        if cambios:
            actualizadas.append({"id": f.id, "nombre": f.nombre_frontera, "cambios": cambios})
            if not dry_run:
                for attr, valor in cambios.items():
                    setattr(f, attr, valor)
        else:
            sin_info.append({"id": f.id, "nombre": f.nombre_frontera})

    if not dry_run and actualizadas:
        db.commit()

    return {
        "dry_run": dry_run,
        "total_candidatas": len(fronteras),
        "actualizadas": len(actualizadas),
        "sin_info_en_quoia": len(sin_info),
        "detalle": actualizadas,
    }


@router.post("/backfill-medidor")
def backfill_medidor(
    dry_run: bool = Query(True, description="Solo previsualizar sin escribir"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Backfill de marca/modelo/serie de medidor (principal y respaldo) desde
    Quoia para fronteras existentes que les falte ese dato. Idempotente y
    nunca pisa un valor ya diligenciado. Con dry_run=true solo reporta."""
    return _backfill_medidor_info(db, dry_run=dry_run)


def _normalizar_nombre_operador(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def _backfill_operador_red_info(db: Session, dry_run: bool = True) -> dict:
    """Vincula al catálogo (`operadores_red`) los proyectos cuyo
    `operador_red` de texto libre YA diligenciado coincide (normalizado, sin
    tildes/mayúsculas) con el `nombre_legal`/`nombre_comercial` de un
    operador -- y cascada el vínculo hacia sus fronteras que todavía no lo
    tengan. Nunca pisa un `operador_red_id` ya diligenciado en ningún lado.
    Sin botón en el frontend a propósito (mismo criterio que
    backfill-medidor): se corre puntualmente cuando haga falta."""
    catalogo = db.query(OperadorRed).all()
    por_nombre: dict[str, int] = {}
    for o in catalogo:
        por_nombre[_normalizar_nombre_operador(o.nombre_legal)] = o.id
        if o.nombre_comercial:
            por_nombre[_normalizar_nombre_operador(o.nombre_comercial)] = o.id

    proyectos = (
        db.query(Proyecto)
        .options(selectinload(Proyecto.fronteras))
        .filter(Proyecto.operador_red_id.is_(None), Proyecto.operador_red.isnot(None))
        .all()
    )

    actualizados = []
    sin_match = []
    for p in proyectos:
        operador_id = por_nombre.get(_normalizar_nombre_operador(p.operador_red))
        if operador_id is None:
            sin_match.append({"id": p.id, "nombre": p.nombre_comercial, "operador_red_texto": p.operador_red})
            continue
        fronteras_afectadas = [f.id for f in p.fronteras if f.operador_red_id is None]
        actualizados.append({
            "id": p.id, "nombre": p.nombre_comercial, "operador_red_texto": p.operador_red,
            "operador_red_id": operador_id, "fronteras_afectadas": fronteras_afectadas,
        })
        if not dry_run:
            p.operador_red_id = operador_id
            sincronizar_operador_red(db, p)

    if not dry_run and actualizados:
        db.commit()

    return {
        "dry_run": dry_run,
        "total_candidatos": len(proyectos),
        "actualizados": len(actualizados),
        "sin_match": len(sin_match),
        "detalle": actualizados,
        "detalle_sin_match": sin_match,
    }


@router.post("/backfill-operador-red")
def backfill_operador_red(
    dry_run: bool = Query(True, description="Solo previsualizar sin escribir"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Vincula al catálogo de operadores los proyectos/fronteras cuyo texto
    libre ya diligenciado coincide con un operador existente. Idempotente,
    nunca pisa un vínculo ya hecho. Sin botón en el frontend (se corre
    puntualmente, ver comentario en `_backfill_operador_red_info`)."""
    return _backfill_operador_red_info(db, dry_run=dry_run)


# ── Quoia endpoints (legacy: token estatico, medidores/nodos) ──────────────────

@router.get("/quoia/meters")
def quoia_meters(
    search: str = Query("", description="Filter meters by name"),
    _=Depends(get_current_user),
):
    """All Quoia smart meters (300 total)."""
    client = _get_quoia()
    meters = client.get_meters(search=search)
    stats = {"total": len(meters)}
    for m in meters:
        name = (m.get("name") or "").lower()
        if name.startswith("mgs"):
            stats["mgs"] = stats.get("mgs", 0) + 1
        elif name.startswith("minigranja"):
            stats["minigranja"] = stats.get("minigranja", 0) + 1
        elif name.startswith("gd"):
            stats["gd"] = stats.get("gd", 0) + 1
    return {"stats": stats, "meters": meters}


@router.get("/quoia/meters/{meter_id}/curves")
def quoia_meter_curves(meter_id: int, _=Depends(get_current_user)):
    """Typical consumption/generation curves for a meter (7 weekdays x 96 points)."""
    client = _get_quoia()
    curves = client.get_typical_curves(node_id=meter_id)
    if not curves:
        return {"meter_id": meter_id, "curves": []}

    summary = []
    for c in curves:
        iae = c.get("iae", [])
        eae = c.get("eae", [])
        summary.append({
            "weekday": c.get("weekday"),
            "quality_score": c.get("quality_score"),
            "days_used": c.get("days_used"),
            "total_import_kwh": round(sum(iae), 2) if iae else 0,
            "total_export_kwh": round(sum(eae), 2) if eae else 0,
            "iae": iae,
            "eae": eae,
        })
    return {"meter_id": meter_id, "curves": summary}


# ── Diagrama Fasorial ──────────────────────────────────────────────────────────

class FasorialLecturaOut(BaseModel):
    """Última lectura del medidor (tensiones y corrientes por fase) desde Quoia."""
    vp1: float | None
    vp2: float | None
    vp3: float | None
    cp1: float | None
    cp2: float | None
    cp3: float | None
    last_time: str | None = None


@router.get("/fasorial/nodos", tags=["Fronteras"])
def fasorial_nodos(_=Depends(get_current_user)):
    """Lista de nodos/medidores de Quoia (vía Gaia) para el selector del fasorial."""
    gaia = _get_gaia()
    out = [
        {"id": int(n["id"]), "name": n.get("name") or f"Nodo {n['id']}"}
        for n in _list_gaia_nodes(gaia)
        if n.get("id") is not None
    ]
    out.sort(key=lambda x: x["name"].lower())
    return {"total": len(out), "nodos": out}


@router.get("/fasorial/lectura/{node_id}", response_model=FasorialLecturaOut, tags=["Fronteras"])
def fasorial_lectura(
    node_id: int,
    _=Depends(get_current_user),
):
    """Devuelve la lectura más reciente del nodo (hoy) para el diagrama fasorial.

    Toma el snapshot eléctrico del nodo y extrae tensiones (vp1/2/3) y corrientes
    (cp1/2/3) de fase. Si el nodo no tiene lectura disponible hoy, responde 422.
    """
    gaia = _get_gaia()
    snap = gaia.get_node_electrical_snapshot(node_id)
    if not snap:
        raise HTTPException(422, "No fue posible obtener la información del medidor")

    vp = (snap.get("vp1"), snap.get("vp2"), snap.get("vp3"))
    cp = (snap.get("cp1"), snap.get("cp2"), snap.get("cp3"))
    if all(v is None for v in vp) and all(c is None for c in cp):
        raise HTTPException(422, "No fue posible obtener la información del medidor")

    return FasorialLecturaOut(
        vp1=vp[0], vp2=vp[1], vp3=vp[2],
        cp1=cp[0], cp2=cp[1], cp3=cp[2],
        last_time=snap.get("last_time"),
    )


class FasorialInput(BaseModel):
    titulo: str
    vp1: float
    vp2: float
    vp3: float
    cp1: float
    cp2: float
    cp3: float


@router.post("/fasorial/generar", tags=["Fronteras"])
def generar_fasorial(
    body: FasorialInput,
    _=Depends(get_current_user),
):
    """Genera y retorna el diagrama fasorial trifásico como imagen JPEG."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.lines import Line2D
    except ImportError as exc:
        raise HTTPException(500, f"matplotlib no disponible: {exc}")

    vp = [body.vp1, body.vp2, body.vp3]
    cp = [body.cp1, body.cp2, body.cp3]

    ang_v    = [90, 330, 210]
    ang_c    = list(ang_v)

    colors_v = ["#E84040", "#2ECC71", "#3B82F6"]
    colors_c = ["#FF8C8C", "#7EEFC1", "#93C5FD"]
    labels_v = ["V₁ (R)", "V₂ (S)", "V₃ (T)"]
    labels_c = ["I₁ (R)", "I₂ (S)", "I₃ (T)"]

    v_max   = max(vp);  c_max = max(cp)
    radius  = 1.0;      c_scale = 0.55
    v_norm  = [v / v_max * radius for v in vp]
    c_norm  = [c / c_max * c_scale for c in cp]

    fig, ax = plt.subplots(figsize=(11, 11), dpi=150, facecolor="#0D1117")
    ax.set_facecolor("#0D1117")
    ax.set_aspect("equal")

    for r in np.linspace(0.25, 1.15, 4):
        ax.add_patch(plt.Circle((0, 0), r, color="#2C3E50", lw=0.6,
                                linestyle="--", fill=False, zorder=1))

    for deg in range(0, 360, 30):
        rad = np.radians(deg)
        ax.plot([0, 1.18 * np.cos(rad)], [0, 1.18 * np.sin(rad)],
                color="#2C3E50", lw=0.5, zorder=1)
        ax.text(1.22 * np.cos(rad), 1.22 * np.sin(rad), f"{deg}°",
                ha="center", va="center", fontsize=6.5,
                color="#5B7A99", fontfamily="monospace")

    ax.axhline(0, color="#3D5166", lw=0.8, zorder=1)
    ax.axvline(0, color="#3D5166", lw=0.8, zorder=1)

    for i in range(3):
        rad = np.radians(ang_v[i])
        xv, yv = v_norm[i] * np.cos(rad), v_norm[i] * np.sin(rad)
        ax.annotate("", xy=(xv, yv), xytext=(0, 0),
                    arrowprops=dict(arrowstyle="->", color=colors_v[i],
                                   lw=2.8, mutation_scale=20))
        off = 0.09
        ax.text(xv + off * np.cos(rad), yv + off * np.sin(rad),
                f"{labels_v[i]}\n{vp[i]:,.2f} V",
                ha="center", va="center", fontsize=9,
                color=colors_v[i], fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#151C26",
                          edgecolor=colors_v[i], alpha=0.85, lw=1))

    for i in range(3):
        rad = np.radians(ang_c[i])
        xi, yi = c_norm[i] * np.cos(rad), c_norm[i] * np.sin(rad)
        ax.annotate("", xy=(xi, yi), xytext=(0, 0),
                    arrowprops=dict(arrowstyle="->", color=colors_c[i],
                                   lw=1.8, mutation_scale=16,
                                   linestyle="dashed"))
        off2 = -0.12
        ax.text(xi + off2 * np.cos(rad), yi + off2 * np.sin(rad),
                f"{labels_c[i]}\n{cp[i]:.3f} A",
                ha="center", va="center", fontsize=8,
                color=colors_c[i],
                bbox=dict(boxstyle="round,pad=0.25", facecolor="#0D1117",
                          edgecolor=colors_c[i], alpha=0.75, lw=0.8))

    ax.plot(0, 0, "o", color="white", ms=5, zorder=10)

    lim = 1.40
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.axis("off")

    ax.add_patch(mpatches.FancyBboxPatch(
        (-lim * 0.97, -lim * 0.97), lim * 1.94, lim * 1.94,
        boxstyle="round,pad=0.02", linewidth=2,
        edgecolor="#1E3A5F", facecolor="none", zorder=20))

    fig.text(0.5, 0.965, body.titulo.upper(), ha="center", va="top",
             fontsize=22, fontweight="bold", color="#FFFFFF",
             fontfamily="DejaVu Sans", transform=fig.transFigure)
    fig.text(0.5, 0.930, "Diagrama Fasorial — Sistema Trifásico",
             ha="center", va="top", fontsize=11, color="#7EB4E2",
             transform=fig.transFigure)
    fig.add_artist(Line2D([0.08, 0.92], [0.918, 0.918],
                   transform=fig.transFigure, color="#1E4D7B", lw=1.5))

    anomalias = [labels_v[i] for i in range(3) if vp[i] < v_max * 0.10]
    if anomalias:
        msg = "⚠  " + ", ".join(anomalias) + " — Posible falla o pérdida de fase"
        fig.text(0.5, 0.905, msg, ha="center", va="top", fontsize=9.5,
                 color="#FFD700",
                 bbox=dict(boxstyle="round,pad=0.35", facecolor="#2A1A00",
                           edgecolor="#FFD700", alpha=0.9, lw=1.2),
                 transform=fig.transFigure)

    legend_items = []
    for i in range(3):
        legend_items.append(mpatches.Patch(color=colors_v[i],
                             label=f"{labels_v[i]}: {vp[i]:,.2f} V"))
    for i in range(3):
        legend_items.append(mpatches.Patch(color=colors_c[i],
                             label=f"{labels_c[i]}: {cp[i]:.3f} A"))

    ax.legend(handles=legend_items, loc="lower left",
              bbox_to_anchor=(0.01, 0.01), fontsize=8.5,
              framealpha=0.7, facecolor="#111827",
              edgecolor="#1E4D7B", labelcolor="white", ncol=2)

    fig.text(0.5, 0.035,
             "Ángulos: V₁=90° | V₂=330° | V₃=210°   •   Unergy",
             ha="center", va="bottom", fontsize=7.5,
             color="#4A6B8A", transform=fig.transFigure)

    fig.text(0.5, 0.5, "UNERGY", ha="center", va="center",
             fontsize=72, fontweight="bold", color="#FFFFFF",
             alpha=0.045, rotation=30, transform=fig.transFigure,
             fontfamily="DejaVu Sans", zorder=0)

    plt.tight_layout(rect=[0, 0.05, 1, 0.89])

    buf = io.BytesIO()
    plt.savefig(buf, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor(), format="jpeg")
    plt.close(fig)
    buf.seek(0)

    filename = body.titulo.replace(" ", "_").replace("/", "-") + "_Fasorial.jpg"
    return StreamingResponse(
        buf,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
