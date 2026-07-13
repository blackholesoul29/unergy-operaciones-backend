"""
Alertas operativas basadas en el estado del GESCON/ASIC.

Vigencia GESCON: resuelta por `app/utils/gescon_vigencia.resolver_vigencias`
(el mismo núcleo de `_resolve_gescon` de Cumplimiento y de GET /asic). Una fila
es la versión vigente de su SIC solo si ningún relevo/modificación posterior la
superó — procesando cronológicamente por `fecha_inicio` (cuándo tomó efecto),
no por `fecha_solicitud` (cuándo se radicó; ordenar por radicación era el bug
histórico documentado en el docstring de `_resolve_gescon`).

Activo hoy = versión vigente + tipo != 'terminacion' + fecha_fin efectiva >= hoy.
(El DISTINCT ON anterior por fecha_solicitud contaba filas ya relevadas: una
planta reubicada de contrato aparecía "activa en 2+ contratos a la vez".)
"""
from datetime import date
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.proyectos import Proyecto
from app.models.asic import AsicSolicitud, TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.models.cumplimiento import CumplimientoMensual
from app.models.contratos import PPAContrato
from app.schemas.asic_status import AsicStatus
from app.services.asic_monitor import get_ppa_asic_status
from app.utils.gescon_vigencia import resolver_vigencias

router = APIRouter(prefix="/alertas", tags=["Alertas"])


@router.get("/contratos-ppa")
def alertas_contratos_ppa(db: Session = Depends(get_db), _=Depends(get_current_user)):
    hoy = date.today()

    # ── 1. Universo publicado + resolución de vigencia efectiva ─────────────
    records = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud != TipoSolicitudAsicEnum.desistimiento,
            AsicSolicitud.codigo_sic_contrato.isnot(None),
        )
        .order_by(
            AsicSolicitud.fecha_inicio.asc().nullsfirst(),
            AsicSolicitud.fecha_solicitud.asc().nullsfirst(),
            AsicSolicitud.created_at.asc(),
        )
        .all()
    )
    # hasta=hoy: un relevo/modificación con efecto FUTURO aún no desplaza a la
    # versión vigente de hoy (mismo principio del bug histórico de ordenar por
    # fecha_solicitud). La pregunta de este endpoint es "¿qué está activo HOY?".
    vigencias = resolver_vigencias(records, hasta=hoy)

    # ── 2. Activos hoy: versión vigente + fecha_fin efectiva >= hoy ─────────
    sics_por_proyecto: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        v = vigencias[r.id]
        if not v.vigente:
            continue
        if r.tipo_solicitud == TipoSolicitudAsicEnum.terminacion:
            continue
        fin = v.fecha_fin_efectiva
        if fin is None or fin < hoy:
            # None (abierta) excluida por paridad con el comportamiento previo.
            continue
        if r.proyecto_id:
            sics_por_proyecto[r.proyecto_id].append({
                "id": r.id,
                "codigo_sic_contrato": r.codigo_sic_contrato,
                "contrato_interno": r.contrato_interno,
                "tipo_solicitud": getattr(r.tipo_solicitud, "value", r.tipo_solicitud),
                "fecha_inicio": r.fecha_inicio,
                # ventana EFECTIVA: es la que define la simultaneidad real
                "fecha_fin": fin,
                "porcentaje_fncer": r.porcentaje_fncer,
                "es_duplicado": bool(r.es_duplicado),
            })

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
    # Solo cuenta la duplicidad SIN resolver: los registros marcados es_duplicado
    # (compra en bolsa) ya declararon su cruce y no deben volver a alertar.
    proyecto_idx = {p.id: p for p in proyectos}
    duplicados = []
    for pid, sics in sics_por_proyecto.items():
        sin_resolver = [s for s in sics if not s["es_duplicado"]]
        if len(sin_resolver) < 2:
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
                        for s in sin_resolver
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


def generar_alertas_riesgo_asic(
    db: Session,
    umbral_dias: int | None = None,
    hoy: date | None = None,
) -> list[dict]:
    """Alertas de PPA activo sin cobertura ASIC publicada.

    Payload estandarizado (no se persiste: no hay tabla de alertas — este módulo
    las calcula al vuelo, igual que las de contratos y cumplimiento). Pensado
    para consumirse desde el endpoint o desde un job periódico.

    Severidad ALTA en ambos casos críticos: con el contrato ACTIVO, tanto "nada
    radicado" como "radicado hace semanas sin publicar" significan lo mismo hoy
    —la energía se está entregando sin que el ASIC reconozca el contrato—.
    """
    criticos = get_ppa_asic_status(db, is_critical_only=True, umbral_dias=umbral_dias, hoy=hoy)

    alertas = []
    for c in criticos:
        if c.asic_status == AsicStatus.NINGUNA:
            mensaje = "PPA activo sin asignación ASIC publicada"
        else:
            dias = f" (radicado hace {c.dias_pendiente} días)" if c.dias_pendiente is not None else ""
            mensaje = f"PPA activo con registro GESCON sin publicar{dias}"
        alertas.append({
            "tipo": "RIESGO_ASIC",
            "ppa_id": c.ppa_id,
            "mensaje": mensaje,
            "severidad": "ALTA",
            # Contexto para la UI (no forma parte del contrato mínimo del spec).
            "ppa_nombre": c.ppa_nombre,
            "numero_codigo_contrato": c.numero_codigo_contrato,
            "asic_status": c.asic_status.value,
            "asic_solicitud_id": c.asic_solicitud_id,
            "dias_pendiente": c.dias_pendiente,
        })
    return alertas


@router.get("/riesgo-asic")
def alertas_riesgo_asic(
    umbral_dias: int | None = Query(
        None, ge=0,
        description="Días radicado sin publicar antes de que un PENDIENTE alerte. Default: ASIC_ALERTA_DIAS.",
    ),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """PPA activos sin cobertura ASIC publicada hoy. Ver `app.services.asic_monitor`."""
    hoy = date.today()
    alertas = generar_alertas_riesgo_asic(db, umbral_dias=umbral_dias)
    return {
        "fecha_consulta": str(hoy),
        "total_alertas": len(alertas),
        "alertas": alertas,
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

    return {
        "fecha_consulta": str(hoy),
        "periodo": {"anio": year, "mes": month},
        "umbral_pct": umbral_pct,
        "total_alertas": len(alertas),
        "alertas": alertas,
    }
