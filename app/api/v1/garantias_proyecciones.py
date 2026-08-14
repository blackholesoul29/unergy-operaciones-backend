"""Proyecciones de garantía (precobro XM): cálculo en vivo + snapshot semanal."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services.garantias_proyecciones import (
    construir_proyecciones_live,
    guardar_snapshot,
    historial_snapshots,
)

router = APIRouter(prefix="/garantias/proyecciones", tags=["Garantías · Proyecciones"])


@router.get("")
def get_proyecciones(
    plantas_nuevas: int = Query(0, ge=0),
    kwh_planta_nueva: float = Query(180.0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Las dos estimaciones de garantía al corte de hoy (en vivo, sin guardar)."""
    return construir_proyecciones_live(db, plantas_nuevas=plantas_nuevas,
                                       kwh_planta_nueva=kwh_planta_nueva)


@router.post("/snapshot")
def post_snapshot(
    plantas_nuevas: int = Query(0, ge=0),
    kwh_planta_nueva: float = Query(180.0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Calcula y guarda el snapshot semanal (una fila por ventana)."""
    resultado = construir_proyecciones_live(db, plantas_nuevas=plantas_nuevas,
                                            kwh_planta_nueva=kwh_planta_nueva)
    filas = guardar_snapshot(db, resultado)
    return {"guardadas": len(filas), "fecha_corte": resultado.get("fecha_corte")}


@router.get("/historial")
def get_historial(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Snapshots guardados, más recientes primero."""
    filas = historial_snapshots(db)
    return {"snapshots": [
        {"id": f.id, "fecha_corte": f.fecha_corte.isoformat(), "clave": f.clave,
         "anio": f.anio, "mes": f.mes,
         "neto_mwh": float(f.neto_mwh) if f.neto_mwh is not None else None,
         "precio_bolsa": float(f.precio_bolsa) if f.precio_bolsa is not None else None,
         "garantia_total": float(f.garantia_total) if f.garantia_total is not None else None,
         "regulatorio_fallback": f.regulatorio_fallback}
        for f in filas
    ]}
