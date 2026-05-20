from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera, FronteraLectura
from app.schemas.fronteras import (
    FronteraCreate, FronteraUpdate, FronteraOut,
    FronteraLecturaOut, FronteraResumen,
)
from app.services.mgs.quoia_client import QuoiaClient

router = APIRouter(prefix="/fronteras", tags=["Fronteras"])

_quoia: QuoiaClient | None = None


def _get_quoia() -> QuoiaClient:
    global _quoia
    if _quoia is None:
        _quoia = QuoiaClient()
    if not _quoia.enabled:
        raise HTTPException(503, "QUOIA_API_TOKEN not configured")
    return _quoia


def _to_out(f: Frontera) -> FronteraOut:
    d = FronteraOut.model_validate(f)
    if f.proyecto:
        d.proyecto_nombre = f.proyecto.nombre_comercial
    return d


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
    estado_operacional: str | None = Query(None, description="Filter by estado_operacional"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        db.query(Frontera)
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.deleted_at.is_(None))
    )
    if proyecto_id:
        q = q.filter(Frontera.proyecto_id == proyecto_id)
    if estado_operacional:
        q = q.filter(Frontera.estado_operacional == estado_operacional)
    return [_to_out(f) for f in q.order_by(Frontera.codigo_frontera).all()]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=FronteraOut, status_code=201)
def create_frontera(
    body: FronteraCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if body.codigo_frontera:
        existing = db.query(Frontera).filter_by(codigo_frontera=body.codigo_frontera).first()
        if existing:
            for k, v in body.model_dump(exclude_none=True).items():
                setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return _to_out(db.query(Frontera).options(joinedload(Frontera.proyecto)).filter(Frontera.id == existing.id).first())
    obj = Frontera(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _to_out(db.query(Frontera).options(joinedload(Frontera.proyecto)).filter(Frontera.id == obj.id).first())


# ── Detail ────────────────────────────────────────────────────────────────────

@router.get("/{frontera_id}", response_model=FronteraOut)
def get_frontera(
    frontera_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f = (
        db.query(Frontera)
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None))
        .first()
    )
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    return _to_out(f)


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
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None))
        .first()
    )
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return _to_out(
        db.query(Frontera)
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.id == f.id)
        .first()
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


# ── Quoia endpoints ───────────────────────────────────────────────────────────

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
