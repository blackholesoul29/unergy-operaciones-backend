from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, joinedload, selectinload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera, FronteraLectura, FronteraQuoiaIgnorada
from app.models.operadores_red import OperadorRed
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion
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


CORRIDAS_VENTANA_GENERANDO = 3


def _ultimas_generaciones(db: Session, frontera_ids: list[int]) -> dict[int, list[ReporteEnergiaGeneracion]]:
    """Últimas corridas (por fecha) de reporte_energia_generacion por
    frontera, hasta CORRIDAS_VENTANA_GENERANDO. 'genera de verdad' se decide
    contra esta ventana corta -- no la sola corrida más reciente -- para que
    un día nublado o una falla puntual de medidor no apague la bandera de una
    planta que sigue operando. Tampoco es un umbral fijo de días calendario:
    el pipeline todavía no corre con cadencia diaria estricta (ver memoria de
    sesión), así que se cuentan corridas disponibles, no días del calendario."""
    if not frontera_ids:
        return {}
    filas = (
        db.query(ReporteEnergiaGeneracion)
        .filter(ReporteEnergiaGeneracion.frontera_id.in_(frontera_ids))
        .order_by(ReporteEnergiaGeneracion.frontera_id, ReporteEnergiaGeneracion.fecha.desc())
        .all()
    )
    ultimas: dict[int, list[ReporteEnergiaGeneracion]] = {}
    for fila in filas:
        lista = ultimas.setdefault(fila.frontera_id, [])
        if len(lista) < CORRIDAS_VENTANA_GENERANDO:
            lista.append(fila)
    return ultimas


def _to_out(f: Frontera, db: Session, corridas_generacion: list | None = "sin_dato") -> FronteraOut:
    d = FronteraOut.model_validate(f)
    if f.proyecto:
        d.proyecto_nombre = f.proyecto.nombre_comercial
        d.proyecto_fecha_inicio_comercializacion = f.proyecto.fecha_inicio_comercializacion
        d.clientes_cgm = [
            {**c, "correos": get_contactos(db, "cgm", cliente_id=c["id"])}
            for c in get_clientes_contacto(db, "cgm", f.proyecto_id)
        ]
    if f.operador:
        d.operador_red_id = f.operador.id
        d.operador_comercial = f.operador.nombre_comercial or f.operador.nombre_legal
        d.operador_correos = [c.email for c in f.operador.contactos]

    # "sin_dato" (default) marca que no se pidió este dato en batch para esta
    # llamada (endpoints de un solo objeto) -- se consulta puntual. Lista
    # vacía/None explícito (pasado desde list_fronteras) significa "sí se
    # consultó en batch y esta frontera no tiene ninguna corrida todavía".
    corridas = _ultimas_generaciones(db, [f.id]).get(f.id, []) if corridas_generacion == "sin_dato" else (corridas_generacion or [])
    if corridas:
        d.generando_actual = any(c.energia_final_kwh is not None and c.energia_final_kwh > 0 for c in corridas)
        d.fecha_ultima_generacion = corridas[0].fecha
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
    fronteras = q.order_by(Frontera.codigo_frontera).offset(skip).limit(limit).all()
    generaciones = _ultimas_generaciones(db, [f.id for f in fronteras])
    return [_to_out(f, db, generaciones.get(f.id)) for f in fronteras]


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
