from datetime import date, datetime, timedelta, timezone
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.fronteras import Frontera, FronteraLectura
from app.models.proyectos import Proyecto
from app.models.operadores_red import OperadorRed
from app.schemas.fronteras import (
    FronteraCreate, FronteraUpdate, FronteraOut,
    FronteraLecturaCreate, FronteraLecturaOut, FronteraResumen,
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
        if f.proyecto.cliente:
            d.cliente_id = f.proyecto.cliente.id
            d.cliente_nombre = f.proyecto.cliente.razon_social_nombre
            d.cliente_correos_cgm = f.proyecto.cliente.correos_cgm or []
    if f.operador:
        d.operador_comercial = f.operador.nombre_comercial or f.operador.nombre_legal
        d.operador_correos = [c.email for c in f.operador.contactos]
    return d


_FRONTERA_OPTS = (
    joinedload(Frontera.proyecto).joinedload(Proyecto.cliente),
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
    estado_operacional: str | None = Query(None, description="Filter by estado_operacional"),
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
    if estado_operacional:
        q = q.filter(Frontera.estado_operacional == estado_operacional)
    if tipo_frontera:
        q = q.filter(Frontera.tipo_frontera == tipo_frontera)
    if estado:
        q = q.filter(Frontera.estado == estado)
    return [_to_out(f) for f in q.order_by(Frontera.codigo_frontera).offset(skip).limit(limit).all()]


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
            return _to_out(db.query(Frontera).options(*_FRONTERA_OPTS).filter(Frontera.id == existing.id).first())
    obj = Frontera(**body.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _to_out(db.query(Frontera).options(*_FRONTERA_OPTS).filter(Frontera.id == obj.id).first())


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
        .options(*_FRONTERA_OPTS)
        .filter(Frontera.id == frontera_id, Frontera.deleted_at.is_(None))
        .first()
    )
    if not f:
        raise HTTPException(404, "Frontera no encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return _to_out(
        db.query(Frontera)
        .options(*_FRONTERA_OPTS)
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


# ── Diagrama Fasorial ──────────────────────────────────────────────────────────

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
