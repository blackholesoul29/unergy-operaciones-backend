"""Backfill de `fronteras.fecha_registro_asic` desde el `init_date` de Quoia.

Desde 2026-07-28, `confirmar_frontera_quoia` (app/api/v1/fronteras.py) copia el
`init_date` del border de Quoia a esta columna al confirmar una frontera nueva
-- pero eso solo aplica hacia adelante. Este backfill llena retroactivamente
las fronteras que ya existian en la base antes de ese cambio.

Por defecto solo toca fronteras con `fecha_registro_asic IS NULL` (no
sobreescribe una fecha ya diligenciada a mano); `force=True` recalcula todas.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.fronteras import Frontera
from app.services.mgs.gaia_client import GaiaClient


def _mapa_init_dates(gaia: GaiaClient) -> dict[str, str] | None:
    """frt_code (minusculas) -> init_date (string YYYY-MM-DD), de todos los
    borders de Quoia (generacion y consumo). None si la consulta a Quoia
    falló -- distinto de {} (Quoia respondió pero sin bordes), para no
    confundir una caída de Quoia con "ningún código tiene init_date"."""
    borders = gaia.get_all_borders()
    if gaia.ultima_llamada_fallo:
        return None
    mapa: dict[str, str] = {}
    for border in borders:
        for key in ("frt_generation", "frt_consumption"):
            frt = border.get(key)
            if not frt:
                continue
            code = (frt.get("frt_code") or "").strip().lower()
            init_date = frt.get("init_date")
            if code and init_date:
                mapa[code] = init_date
    return mapa


def backfill_fecha_registro_asic(db: Session, apply: bool = False, force: bool = False) -> dict:
    gaia = GaiaClient()
    if not gaia.enabled:
        return {"ok": False, "error": "Credenciales de Gaia/Quoia no configuradas (GAIA_USER/GAIA_PASS)"}

    init_dates = _mapa_init_dates(gaia)
    if init_dates is None:
        return {"ok": False, "error": "No se pudo consultar Quoia -- intenta de nuevo en un momento"}

    q = db.query(Frontera).filter(
        Frontera.deleted_at.is_(None),
        Frontera.codigo_frontera.isnot(None),
    )
    if not force:
        q = q.filter(Frontera.fecha_registro_asic.is_(None))
    fronteras = q.order_by(Frontera.codigo_frontera).all()

    actualizadas: list[dict] = []
    sin_match: list[dict] = []

    for f in fronteras:
        code = (f.codigo_frontera or "").strip().lower()
        init_date = init_dates.get(code)
        if not init_date:
            sin_match.append({
                "id": f.id, "codigo": f.codigo_frontera, "nombre": f.nombre_frontera,
                "motivo": "codigo_frontera ya no aparece en Quoia",
            })
            continue
        try:
            fecha = date.fromisoformat(init_date)
        except ValueError:
            sin_match.append({
                "id": f.id, "codigo": f.codigo_frontera, "nombre": f.nombre_frontera,
                "motivo": f"init_date invalido: {init_date!r}",
            })
            continue

        anterior = f.fecha_registro_asic
        if apply:
            f.fecha_registro_asic = fecha
        actualizadas.append({
            "id": f.id, "codigo": f.codigo_frontera, "nombre": f.nombre_frontera,
            "fecha": fecha.isoformat(),
            "anterior": anterior.isoformat() if anterior else None,
        })

    if apply:
        db.commit()

    return {
        "ok": True,
        "revisadas": len(fronteras),
        "actualizadas": actualizadas,
        "sin_match": sin_match,
    }
