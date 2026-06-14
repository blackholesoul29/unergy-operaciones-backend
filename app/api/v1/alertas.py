"""
Alertas operativas basadas en el estado del GESCON/ASIC.

Lógica GESCON (GESCON_LOGICA.md):
- Por cada SIC, el estado vigente es el de la última solicitud publicada
  (excluye desistimientos), ordenada por fecha_solicitud DESC.
- Activo = tipo != 'terminacion' AND fecha_fin >= hoy.

Usa DISTINCT ON (PostgreSQL) para obtener la última fila por SIC en una sola
pasada — mucho más eficiente que la alternativa subquery+join.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.api.v1.notificaciones import create_notificacion_alerta
from app.models.proyectos import Proyecto
from app.models.cumplimiento import CumplimientoMensual
from app.models.contratos import PPAContrato
from app.models.notificaciones import NotificacionAlerta
from app.models.usuarios import RolEnum, Usuario

logger = logging.getLogger("alertas")

router = APIRouter(prefix="/alertas", tags=["Alertas"])

# Roles que reciben notificaciones proactivas de alertas de contratos PPA.
_ROLES_NOTIFICABLES = (
    RolEnum.admin.value,
    RolEnum.operaciones.value,
    RolEnum.liquidaciones.value,
)
# Ventana anti-duplicados: no re-notificar la misma alerta_ref dentro de este lapso.
_DEDUP_WINDOW = timedelta(hours=24)


def _emitir_notificaciones_alerta(db: Session, alerta_ref: str, titulo: str, mensaje: str) -> None:
    """Crea notificaciones críticas para los usuarios elegibles, sin duplicar.

    No-fatal: cualquier fallo se registra pero nunca interrumpe el flujo de
    cálculo de alertas.
    """
    try:
        desde = datetime.now(timezone.utc) - _DEDUP_WINDOW
        usuarios = (
            db.query(Usuario)
            .filter(Usuario.activo == True, Usuario.rol.in_(_ROLES_NOTIFICABLES))
            .all()
        )
        for u in usuarios:
            ya_existe = (
                db.query(NotificacionAlerta.id)
                .filter(
                    NotificacionAlerta.usuario_id == u.id,
                    NotificacionAlerta.alerta_ref == alerta_ref,
                    NotificacionAlerta.created_at >= desde,
                )
                .first()
            )
            if ya_existe:
                continue
            create_notificacion_alerta(
                db,
                usuario_id=u.id,
                titulo=titulo,
                mensaje=mensaje,
                severidad="critica",
                canal="ambos",
                alerta_ref=alerta_ref,
                email_to=u.email,
            )
    except Exception as exc:  # pragma: no cover — defensivo
        logger.error("Fallo emitiendo notificaciones para %s: %s", alerta_ref, exc)

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
def alertas_contratos_ppa(db: Session = Depends(get_db), _=Depends(get_current_user)):
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


@router.get("/cumplimiento-ppa")
def alertas_cumplimiento_ppa(
    anio: int | None = Query(None, ge=2020, le=2050),
    mes: int | None = Query(None, ge=1, le=12),
    umbral_pct: float = Query(90.0, ge=0, le=100, description="Threshold below which a deficit alert fires (default: 90%)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Alertas de deficit de cumplimiento PPA.

    Genera una alerta por cada contrato cuya generacion real sea menor al
    umbral_pct% de su compromiso de energia. Default: 90%.

    Si anio/mes no se proporcionan, usa el mes actual.
    """
    hoy = date.today()
    year = anio or hoy.year
    month = mes or hoy.month

    rows = (
        db.query(CumplimientoMensual)
        .join(PPAContrato, CumplimientoMensual.contrato_ppa_id == PPAContrato.id)
        .filter(
            CumplimientoMensual.anio == year,
            CumplimientoMensual.mes == month,
        )
        .all()
    )

    alertas = []
    for r in rows:
        gen = float(r.gen_total_mwh) if r.gen_total_mwh is not None else 0
        comp = float(r.compromiso_mwh) if r.compromiso_mwh is not None else None
        if comp is None or comp <= 0:
            continue

        cobertura = (gen / comp) * 100
        if cobertura >= umbral_pct:
            continue

        deficit_mwh = round(comp - gen, 3)
        # Estimate COP impact
        precio = float(r.precio_bolsa_promedio) if r.precio_bolsa_promedio is not None else None
        impacto_cop = round(deficit_mwh * 1000 * precio, 0) if precio is not None else None

        contrato = r.contrato_ppa
        alertas.append({
            "tipo": "deficit_cumplimiento_ppa",
            "severidad": "alta" if cobertura < 80 else "media",
            "contrato_ppa_id": r.contrato_ppa_id,
            "contrato_nombre": contrato.nombre_interno if contrato else None,
            "comprador_nombre": contrato.comprador_nombre if contrato else None,
            "anio": year,
            "mes": month,
            "gen_total_mwh": gen,
            "compromiso_mwh": comp,
            "cobertura_pct": round(cobertura, 1),
            "deficit_mwh": deficit_mwh,
            "impacto_estimado_cop": impacto_cop,
            "precio_bolsa_promedio": precio,
            "mensaje": (
                f"{contrato.nombre_interno or 'Contrato'}: "
                f"deficit de {deficit_mwh:.1f} MWh ({cobertura:.0f}% cobertura)"
                + (f", impacto estimado ${impacto_cop:,.0f} COP" if impacto_cop else "")
            ),
        })

    alertas.sort(key=lambda a: a.get("cobertura_pct", 100))

    # ── Hook: notificar proactivamente las alertas de severidad alta ─────────
    for a in alertas:
        if a["severidad"] != "alta":
            continue
        alerta_ref = f"cumplimiento_ppa:{a['contrato_ppa_id']}:{year}-{month:02d}"
        _emitir_notificaciones_alerta(
            db,
            alerta_ref=alerta_ref,
            titulo=f"Déficit crítico de cumplimiento PPA — {a['contrato_nombre'] or 'Contrato'}",
            mensaje=a["mensaje"],
        )

    return {
        "fecha_consulta": str(hoy),
        "periodo": {"anio": year, "mes": month},
        "umbral_pct": umbral_pct,
        "total_alertas": len(alertas),
        "alertas": alertas,
    }
