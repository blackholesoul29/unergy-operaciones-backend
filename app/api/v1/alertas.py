"""
Alertas operativas basadas en el estado del GESCON/ASIC.
Aplica la lógica GESCON: por cada SIC, el estado vigente es
el de la última solicitud publicada (no desistimiento), ordenada por fecha_solicitud.
"""
from datetime import date
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models.asic import AsicSolicitud
from app.models.proyectos import Proyecto

router = APIRouter(prefix="/alertas", tags=["Alertas"])


def _active_sics(db: Session, hoy: date) -> list[AsicSolicitud]:
    """
    Aplica lógica GESCON: por cada SIC toma la solicitud publicada más reciente
    (excluyendo desistimientos) y retorna las que están activas hoy.
    Activo = tipo != terminacion Y fecha_fin >= hoy.
    """
    # Subconsulta: max(fecha_solicitud) publicada por SIC
    sub = (
        db.query(
            AsicSolicitud.codigo_sic_contrato,
            func.max(AsicSolicitud.fecha_solicitud).label("max_fecha"),
        )
        .filter(
            AsicSolicitud.estado_solicitud == "publicado",
            AsicSolicitud.tipo_solicitud != "desistimiento",
            AsicSolicitud.codigo_sic_contrato.isnot(None),
        )
        .group_by(AsicSolicitud.codigo_sic_contrato)
        .subquery()
    )

    latest = (
        db.query(AsicSolicitud)
        .join(
            sub,
            (AsicSolicitud.codigo_sic_contrato == sub.c.codigo_sic_contrato)
            & (AsicSolicitud.fecha_solicitud == sub.c.max_fecha),
        )
        .filter(
            AsicSolicitud.estado_solicitud == "publicado",
            AsicSolicitud.tipo_solicitud != "desistimiento",
        )
        .all()
    )

    return [
        s for s in latest
        if s.tipo_solicitud != "terminacion"
        and s.fecha_fin is not None
        and s.fecha_fin >= hoy
    ]


@router.get("/contratos-ppa")
def alertas_contratos_ppa(db: Session = Depends(get_db)):
    hoy = date.today()

    active_sics = _active_sics(db, hoy)

    # Proyectos con SIC activo: proyecto_id → lista de SICs
    sics_por_proyecto: dict[int, list[AsicSolicitud]] = defaultdict(list)
    for s in active_sics:
        if s.proyecto_id:
            sics_por_proyecto[s.proyecto_id].append(s)

    proyectos_con_sic = set(sics_por_proyecto.keys())

    # Todos los proyectos que deben estar en GESCON
    # (excluimos autoconsumo y cancelados)
    proyectos = (
        db.query(Proyecto)
        .filter(
            Proyecto.estado != "cancelado",
            Proyecto.tipo_proyecto != "autoconsumo",
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )

    # ── Huérfanos: proyectos sin SIC activo ──────────────────────────────────
    huerfanos = [
        {
            "proyecto_id": p.id,
            "nombre_comercial": p.nombre_comercial,
            "tipo_proyecto": p.tipo_proyecto,
            "estado": p.estado,
        }
        for p in proyectos
        if p.id not in proyectos_con_sic
    ]

    # ── Duplicados: proyectos con 2+ SICs activos ────────────────────────────
    duplicados = []
    for pid, sics in sics_por_proyecto.items():
        if len(sics) < 2:
            continue
        proyecto = next((p for p in proyectos if p.id == pid), None)
        if not proyecto:
            continue
        duplicados.append(
            {
                "proyecto_id": pid,
                "nombre_comercial": proyecto.nombre_comercial,
                "tipo_proyecto": proyecto.tipo_proyecto,
                "sics": [
                    {
                        "id": s.id,
                        "codigo_sic_contrato": s.codigo_sic_contrato,
                        "contrato_interno": s.contrato_interno,
                        "tipo_solicitud": s.tipo_solicitud,
                        "fecha_inicio": str(s.fecha_inicio) if s.fecha_inicio else None,
                        "fecha_fin": str(s.fecha_fin) if s.fecha_fin else None,
                        "porcentaje_fncer": float(s.porcentaje_fncer) if s.porcentaje_fncer else None,
                    }
                    for s in sorted(sics, key=lambda x: x.fecha_inicio or date.min)
                ],
            }
        )

    # Ordenar duplicados por cantidad de SICs desc
    duplicados.sort(key=lambda x: len(x["sics"]), reverse=True)

    return {
        "fecha_consulta": str(hoy),
        "huerfanos": huerfanos,
        "duplicados": duplicados,
    }
