"""Proyecciones de garantía (precobro XM): cálculo en vivo + snapshot semanal."""
from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services.balcttos import neto_compras_bolsa_de_bytes
from app.services.garantias_proyecciones import (
    construir_proyecciones_live,
    guardar_balcttos_neto,
    guardar_snapshot,
    historial_snapshots,
    pagado_por_periodo,
    set_pagado,
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


@router.get("/pagado")
def get_pagado(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Montos de garantía pagados por período."""
    d = pagado_por_periodo(db)
    return {"pagado": [{"anio": a, "mes": m, "valor": v}
                       for (a, m), v in sorted(d.items())]}


@router.put("/pagado")
def put_pagado(
    anio: int = Query(..., ge=2020, le=2050),
    mes: int = Query(..., ge=1, le=12),
    valor: float = Query(..., ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Fija (upsert) el monto pagado de un período."""
    set_pagado(db, anio, mes, valor)
    return {"anio": anio, "mes": mes, "valor": valor}


def ingerir_balcttos(*, anio: int, mes: int, archivo_bytes: bytes, db: Session, _=None) -> dict:
    """Parsea el BalCttos y guarda su neto real. Lógica pura (testeable sin multipart)."""
    parsed = neto_compras_bolsa_de_bytes(archivo_bytes)
    dias = sorted(parsed["por_dia"])
    dia_corte = int(dias[-1][8:10]) if dias else 0
    guardar_balcttos_neto(db, anio, mes, dia_corte=dia_corte, neto_mwh=parsed["total_mwh"])
    return {"anio": anio, "mes": mes, "dia_corte": dia_corte, "neto_mwh": parsed["total_mwh"]}


@router.post("/balcttos")
async def post_balcttos(
    anio: int = Query(..., ge=2020, le=2050),
    mes: int = Query(..., ge=1, le=12),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Recibe el BalCttos (lo empuja el agente local), parsea el NETO DE COMPRAS EN BOLSA
    y guarda el neto real del período."""
    contenido = await archivo.read()
    return ingerir_balcttos(anio=anio, mes=mes, archivo_bytes=contenido, db=db, _=_)
