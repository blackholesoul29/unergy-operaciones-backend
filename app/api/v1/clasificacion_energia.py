"""API estandarizada de clasificación energética mensual (categorías a-f).

Para que cualquier área/sistema consulte el rol de cada planta en el mercado
sin reimplementar la lógica GESCON:

  GET /clasificacion-energia/categorias     → catálogo estandarizado (a-f)
  GET /clasificacion-energia?year&month     → filas del snapshot del mes
      [&categoria=ppa_venta_ungg][&proyecto_id=N][&refresh=true]

El snapshot se materializa en `clasificacion_energia_mensual`. Si el mes no
tiene snapshot (o refresh=true) se recalcula desde GESCON/PPA en la misma
petición — la tabla nunca se edita a mano.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.clasificacion_energia import (
    CATEGORIAS_ENERGIA,
    CATEGORIAS_KEYS,
    ClasificacionEnergiaMensual,
)
from app.services.clasificacion_energia import recalcular_clasificacion

router = APIRouter(prefix="/clasificacion-energia", tags=["Clasificación energía"])


def _vendedor_uso_recurso(r) -> str | None:
    """Para la fila (c) de uso del recurso el vendedor es el cliente (inversionistas
    del proyecto), no el mercado spot."""
    if not r.uso_del_recurso or r.categoria != "bolsa_compra_ungg" or not r.proyecto:
        return None
    nombres = [
        inv.cliente.razon_social_nombre
        for inv in (r.proyecto.inversionistas or [])
        if inv.cliente and inv.cliente.razon_social_nombre
    ]
    return " / ".join(nombres) or None


@router.get("/categorias")
def get_categorias(_=Depends(get_current_user)):
    """Catálogo estandarizado de las 6 categorías (a-f). Estable: `key` es el
    identificador para integraciones."""
    return CATEGORIAS_ENERGIA


@router.get("")
def get_clasificacion(
    year: int = Query(..., ge=2020, le=2050),
    month: int = Query(..., ge=1, le=12),
    categoria: str | None = Query(None, description="key del catálogo, p.ej. ppa_venta_ungg"),
    proyecto_id: int | None = Query(None),
    refresh: bool = Query(False, description="Fuerza recálculo desde GESCON/PPA"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if categoria is not None and categoria not in CATEGORIAS_KEYS:
        raise HTTPException(422, f"Categoría desconocida: {categoria}. Válidas: {sorted(CATEGORIAS_KEYS)}")

    base = db.query(ClasificacionEnergiaMensual).filter(
        ClasificacionEnergiaMensual.anio == year,
        ClasificacionEnergiaMensual.mes == month,
    )
    if refresh or base.first() is None:
        recalcular_clasificacion(db, year, month)

    q = db.query(ClasificacionEnergiaMensual).filter(
        ClasificacionEnergiaMensual.anio == year,
        ClasificacionEnergiaMensual.mes == month,
    )
    if categoria:
        q = q.filter(ClasificacionEnergiaMensual.categoria == categoria)
    if proyecto_id:
        q = q.filter(ClasificacionEnergiaMensual.proyecto_id == proyecto_id)
    rows = q.order_by(
        ClasificacionEnergiaMensual.categoria,
        ClasificacionEnergiaMensual.proyecto_id,
    ).all()

    calculado_en = rows[0].calculado_en.isoformat() if rows else None
    return {
        "year": year,
        "month": month,
        "calculado_en": calculado_en,
        "total": len(rows),
        "items": [
            {
                "categoria": r.categoria,
                "proyecto_id": r.proyecto_id,
                "proyecto_nombre": r.proyecto.nombre_comercial if r.proyecto else None,
                "contrato_ppa_id": r.contrato_ppa_id,
                "contrato_nombre": (
                    (r.contrato_ppa.nombre_interno or r.contrato_ppa.numero_codigo_contrato)
                    if r.contrato_ppa else None
                ),
                "codigo_sic": r.codigo_sic,
                "fecha_inicio": r.fecha_inicio.isoformat() if r.fecha_inicio else None,
                "fecha_fin": r.fecha_fin.isoformat() if r.fecha_fin else None,
                "uso_del_recurso": bool(r.uso_del_recurso),
                "vendedor_nombre": _vendedor_uso_recurso(r),
            }
            for r in rows
        ],
    }
