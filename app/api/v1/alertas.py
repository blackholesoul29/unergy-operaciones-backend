"""
Alertas operativas basadas en el estado del GESCON/ASIC.

Lógica GESCON (GESCON_LOGICA.md):
- Por cada SIC, el estado vigente es el de la última solicitud publicada
  (excluye desistimientos), ordenada por fecha_solicitud DESC.
- Activo = tipo != 'terminacion' AND fecha_fin >= hoy.

Usa DISTINCT ON (PostgreSQL) para obtener la última fila por SIC en una sola
pasada — mucho más eficiente que la alternativa subquery+join.
"""
from datetime import date
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models.proyectos import Proyecto

router = APIRouter(prefix="/alertas", tags=["Alertas"])

_LATEST_SIC_SQL = text("""
    SELECT DISTINCT ON (codigo_sic_contrato)
        id,
        proyecto_id,
        codigo_sic_contrato,
        tipo_solicitud,
        contrato_interno,
        fecha_solicitud,
        fecha_inicio,
        fecha_fin,
        porcentaje_fncer
    FROM asic_solicitudes
    WHERE estado_solicitud = 'publicado'
      AND tipo_solicitud    != 'desistimiento'
      AND codigo_sic_contrato IS NOT NULL
    ORDER BY codigo_sic_contrato, fecha_solicitud DESC NULLS LAST
""")


@router.get("/contratos-ppa")
def alertas_contratos_ppa(db: Session = Depends(get_db)):
    hoy = date.today()

    # ── 1. Latest published solicitud per SIC (single query, DISTINCT ON) ───
    rows = db.execute(_LATEST_SIC_SQL).mappings().all()

    # ── 2. Active SICs: not terminated + fecha_fin >= hoy ───────────────────
    sics_por_proyecto: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r["tipo_solicitud"] == "terminacion":
            continue
        if r["fecha_fin"] is None or r["fecha_fin"] < hoy:
            continue
        if r["proyecto_id"]:
            sics_por_proyecto[r["proyecto_id"]].append(dict(r))

    proyectos_con_sic = set(sics_por_proyecto.keys())

    # ── 3. Non-autoconsumo, non-cancelled projects (only needed columns) ─────
    proyectos = (
        db.query(
            Proyecto.id,
            Proyecto.nombre_comercial,
            Proyecto.tipo_proyecto,
            Proyecto.estado,
        )
        .filter(
            Proyecto.estado != "cancelado",
            Proyecto.tipo_proyecto != "autoconsumo",
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )

    # ── 4. Huérfanos ─────────────────────────────────────────────────────────
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

    # ── 5. Duplicados ─────────────────────────────────────────────────────────
    proyecto_idx = {p.id: p for p in proyectos}
    duplicados = []
    for pid, sics in sics_por_proyecto.items():
        if len(sics) < 2:
            continue
        p = proyecto_idx.get(pid)
        if not p:
            continue
        duplicados.append(
            {
                "proyecto_id": pid,
                "nombre_comercial": p.nombre_comercial,
                "tipo_proyecto": p.tipo_proyecto,
                "sics": sorted(
                    [
                        {
                            "id": s["id"],
                            "codigo_sic_contrato": s["codigo_sic_contrato"],
                            "contrato_interno": s["contrato_interno"],
                            "tipo_solicitud": s["tipo_solicitud"],
                            "fecha_inicio": str(s["fecha_inicio"]) if s["fecha_inicio"] else None,
                            "fecha_fin": str(s["fecha_fin"]) if s["fecha_fin"] else None,
                            "porcentaje_fncer": float(s["porcentaje_fncer"]) if s["porcentaje_fncer"] else None,
                        }
                        for s in sics
                    ],
                    key=lambda x: x["fecha_inicio"] or "",
                ),
            }
        )

    duplicados.sort(key=lambda x: len(x["sics"]), reverse=True)

    return {
        "fecha_consulta": str(hoy),
        "huerfanos": huerfanos,
        "duplicados": duplicados,
    }
