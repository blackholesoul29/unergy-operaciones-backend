import logging
import traceback
from datetime import date, datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Usuario


def _require_liquidaciones_write(current: Usuario = Depends(get_current_user)):
    if current.rol.value not in ("admin", "liquidaciones"):
        raise HTTPException(403, "Se requiere rol admin o liquidaciones")
    return current
from app.models.liquidaciones import (
    Liquidacion, LiquidacionCosto, LiquidacionMandato,
    LiquidacionMandatoLinea, LiquidacionFactura, LiquidacionXMDato,
    TipoCostoEnum, TipoMandatoEnum, TipoLineaMandatoEnum,
    TipoFacturaServicioEnum, EstadoLiquidacionEnum,
    EstadoMandatoEnum, EstadoFacturaEnum,
)
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.contratos import PPATarifa, PPAContrato, ppa_contrato_proyectos_table
from app.models.clientes import Cliente
from app.models.panel_contable import PanelContable
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/liquidaciones", tags=["Liquidaciones"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class LiquidacionCreate(BaseModel):
    proyecto_id: int
    periodo: date
    tipo_venta: str
    observaciones_resultados: str | None = None


class LiquidacionUpdate(BaseModel):
    estado: str | None = None
    estado_resultados_url: str | None = None
    fecha_inicio_proceso: date | None = None
    fecha_firma: date | None = None
    consecutivo_inicial_ingresos: int | None = None
    consecutivo_inicial_costos: int | None = None
    comprobante_contable_ref: str | None = None
    ingresos_energia_cop: float | None = None
    costos_comercializacion_xm_cop: float | None = None
    costos_operativos_cop: float | None = None
    ingreso_neto_cop: float | None = None
    tasa_cambio: float | None = None
    observaciones_resultados: str | None = None


class CostoCreate(BaseModel):
    tipo_costo: str
    descripcion: str
    proveedor: str | None = None
    nro_soporte: str | None = None
    soporte_url: str | None = None
    valor_cop: float


class CostoUpdate(BaseModel):
    tipo_costo: str | None = None
    descripcion: str | None = None
    proveedor: str | None = None
    nro_soporte: str | None = None
    soporte_url: str | None = None
    valor_cop: float | None = None


class MandatoCreate(BaseModel):
    tipo: str
    inversionista_id: int | None = None
    numero_mandato: str | None = None
    consecutivo: int | None = None
    beneficiario_nombre: str | None = None
    beneficiario_nit: str | None = None
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    pa_aplica: bool = False
    categoria_contable: str | None = None
    observaciones: str | None = None


class MandatoUpdate(BaseModel):
    numero_mandato: str | None = None
    consecutivo: int | None = None
    beneficiario_nombre: str | None = None
    beneficiario_nit: str | None = None
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    estado: str | None = None
    fecha_generacion: date | None = None
    fecha_envio_revisoria: date | None = None
    fecha_firma: date | None = None
    pa_aplica: bool | None = None
    categoria_contable: str | None = None
    total_ingresos_cop: float | None = None
    total_costos_cop: float | None = None
    total_retenciones_cop: float | None = None
    total_iva_cop: float | None = None
    valor_neto_cop: float | None = None
    observaciones: str | None = None


class LineaCreate(BaseModel):
    tipo_linea: str
    concepto: str
    valor_cop: float
    porcentaje: float | None = None
    base_calculo_cop: float | None = None
    referencia_factura: str | None = None
    soporte_url: str | None = None
    orden: int = 0


class LineaUpdate(BaseModel):
    tipo_linea: str | None = None
    concepto: str | None = None
    valor_cop: float | None = None
    porcentaje: float | None = None
    base_calculo_cop: float | None = None
    referencia_factura: str | None = None
    soporte_url: str | None = None
    orden: int | None = None


class FacturaCreate(BaseModel):
    tipo_servicio: str
    numero_factura: str | None = None
    nro_soporte: str | None = None
    soporte_url: str | None = None
    valor_cop: float
    fecha_emision: date | None = None
    fecha_vencimiento: date | None = None


class FacturaUpdate(BaseModel):
    numero_factura: str | None = None
    nro_soporte: str | None = None
    soporte_url: str | None = None
    valor_cop: float | None = None
    fecha_emision: date | None = None
    fecha_vencimiento: date | None = None
    estado: str | None = None


class XMDatoCreate(BaseModel):
    frontera_id: int | None = None
    tipo_venta: str
    energia_kwh: float
    tarifa_aplicada_kwh: float
    valor_bruto_cop: float
    referencia_factura_xm: str | None = None
    fecha_factura_xm: date | None = None


class XMDatoUpdate(BaseModel):
    frontera_id: int | None = None
    tipo_venta: str | None = None
    energia_kwh: float | None = None
    tarifa_aplicada_kwh: float | None = None
    valor_bruto_cop: float | None = None
    referencia_factura_xm: str | None = None
    fecha_factura_xm: date | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_liq_or_404(id: int, db: Session) -> Liquidacion:
    liq = (
        db.query(Liquidacion)
        .options(
            selectinload(Liquidacion.proyecto),
            selectinload(Liquidacion.costos),
            selectinload(Liquidacion.facturas),
            selectinload(Liquidacion.mandatos)
                .selectinload(LiquidacionMandato.lineas),
            selectinload(Liquidacion.mandatos)
                .selectinload(LiquidacionMandato.inversionista)
                .selectinload(ProyectoInversionista.cliente),
        )
        .filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None))
        .first()
    )
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    return liq


def _serializar_costo(c: LiquidacionCosto) -> dict:
    return {
        "id": c.id,
        "tipo_costo": c.tipo_costo,
        "descripcion": c.descripcion,
        "proveedor": c.proveedor,
        "nro_soporte": c.nro_soporte,
        "soporte_url": c.soporte_url,
        "valor_cop": float(c.valor_cop) if c.valor_cop is not None else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _serializar_linea(l: LiquidacionMandatoLinea) -> dict:
    return {
        "id": l.id,
        "tipo_linea": str(l.tipo_linea) if l.tipo_linea is not None else None,
        "concepto": l.concepto,
        "valor_cop": float(l.valor_cop) if l.valor_cop is not None else None,
        "porcentaje": float(l.porcentaje) if l.porcentaje is not None else None,
        "base_calculo_cop": float(l.base_calculo_cop) if l.base_calculo_cop is not None else None,
        "referencia_factura": l.referencia_factura,
        "soporte_url": getattr(l, "soporte_url", None),
        "orden": l.orden,
    }


def _serializar_mandato(m: LiquidacionMandato) -> dict:
    inv = None
    if m.inversionista:
        inv = {
            "id": m.inversionista.id,
            "porcentaje_participacion": float(m.inversionista.porcentaje_participacion or 0),
            "es_patrimonio_autonomo": m.inversionista.es_patrimonio_autonomo,
            "cliente_id": m.inversionista.cliente_id,
            "cliente_nombre": m.inversionista.cliente.razon_social_nombre if m.inversionista.cliente else m.beneficiario_nombre,
        }
    return {
        "id": m.id,
        "tipo": m.tipo,
        "numero_mandato": m.numero_mandato,
        "consecutivo": m.consecutivo,
        "beneficiario_nombre": m.beneficiario_nombre,
        "beneficiario_nit": m.beneficiario_nit,
        "estado": m.estado,
        "fecha_generacion": m.fecha_generacion.isoformat() if m.fecha_generacion else None,
        "fecha_envio_revisoria": m.fecha_envio_revisoria.isoformat() if m.fecha_envio_revisoria else None,
        "fecha_firma": m.fecha_firma.isoformat() if m.fecha_firma else None,
        "pa_aplica": m.pa_aplica,
        "categoria_contable": m.categoria_contable,
        "total_ingresos_cop": float(m.total_ingresos_cop) if m.total_ingresos_cop is not None else None,
        "total_costos_cop": float(m.total_costos_cop) if m.total_costos_cop is not None else None,
        "total_retenciones_cop": float(m.total_retenciones_cop) if m.total_retenciones_cop is not None else None,
        "total_iva_cop": float(m.total_iva_cop) if m.total_iva_cop is not None else None,
        "valor_neto_cop": float(m.valor_neto_cop) if m.valor_neto_cop is not None else None,
        "observaciones": m.observaciones,
        "inversionista": inv,
        "lineas": sorted([_serializar_linea(l) for l in m.lineas], key=lambda x: x["orden"]),
    }


def _serializar_factura(f: LiquidacionFactura) -> dict:
    return {
        "id": f.id,
        "proyecto_inversionista_id": f.proyecto_inversionista_id,
        "tipo_servicio": f.tipo_servicio,
        "numero_factura": f.numero_factura,
        "nro_soporte": f.nro_soporte,
        "soporte_url": f.soporte_url,
        "valor_cop": float(f.valor_cop),
        "fecha_emision": f.fecha_emision.isoformat() if f.fecha_emision else None,
        "fecha_vencimiento": f.fecha_vencimiento.isoformat() if f.fecha_vencimiento else None,
        "estado": f.estado,
    }


def _serializar_xm_dato(x: LiquidacionXMDato) -> dict:
    return {
        "id": x.id,
        "frontera_id": x.frontera_id,
        "tipo_venta": x.tipo_venta,
        "energia_kwh": float(x.energia_kwh),
        "tarifa_aplicada_kwh": float(x.tarifa_aplicada_kwh),
        "valor_bruto_cop": float(x.valor_bruto_cop),
        "referencia_factura_xm": x.referencia_factura_xm,
        "fecha_factura_xm": x.fecha_factura_xm.isoformat() if x.fecha_factura_xm else None,
        "created_at": x.created_at.isoformat(),
    }


def _serializar_liquidacion_base(liq: Liquidacion) -> dict:
    return {
        "id": liq.id,
        "proyecto_id": liq.proyecto_id,
        "proyecto_nombre": liq.proyecto.nombre_comercial if liq.proyecto else None,
        "periodo": liq.periodo.isoformat(),
        "tipo_venta": liq.tipo_venta,
        "estado": liq.estado,
        "fecha_inicio_proceso": liq.fecha_inicio_proceso.isoformat() if liq.fecha_inicio_proceso else None,
        "fecha_firma": liq.fecha_firma.isoformat() if liq.fecha_firma else None,
        "consecutivo_inicial_ingresos": liq.consecutivo_inicial_ingresos,
        "consecutivo_inicial_costos": liq.consecutivo_inicial_costos,
        "comprobante_contable_ref": liq.comprobante_contable_ref,
        "estado_resultados_url": liq.estado_resultados_url,
        "ingresos_energia_cop": float(liq.ingresos_energia_cop) if liq.ingresos_energia_cop is not None else None,
        "costos_comercializacion_xm_cop": float(liq.costos_comercializacion_xm_cop) if liq.costos_comercializacion_xm_cop is not None else None,
        "costos_operativos_cop": float(liq.costos_operativos_cop) if liq.costos_operativos_cop is not None else None,
        "ingreso_neto_cop": float(liq.ingreso_neto_cop) if liq.ingreso_neto_cop is not None else None,
        "tasa_cambio": float(liq.tasa_cambio) if liq.tasa_cambio is not None else None,
        "observaciones_resultados": liq.observaciones_resultados,
        "created_at": liq.created_at.isoformat(),
        "updated_at": liq.updated_at.isoformat(),
    }


# ── CRUD Liquidaciones ─────────────────────────────────────────────────────────

@router.get("")
def list_liquidaciones(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    proyecto_id: int | None = None,
    periodo_desde: date | None = None,
    periodo_hasta: date | None = None,
    estado: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Liquidacion).filter(Liquidacion.deleted_at.is_(None)).options(selectinload(Liquidacion.proyecto))
    if proyecto_id:
        q = q.filter(Liquidacion.proyecto_id == proyecto_id)
    if periodo_desde:
        q = q.filter(Liquidacion.periodo >= periodo_desde)
    if periodo_hasta:
        q = q.filter(Liquidacion.periodo <= periodo_hasta)
    if estado:
        q = q.filter(Liquidacion.estado == estado)
    total = q.count()
    items = q.order_by(Liquidacion.periodo.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "items": [_serializar_liquidacion_base(l) for l in items],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


@router.post("", status_code=201)
def create_liquidacion(
    body: LiquidacionCreate,
    db: Session = Depends(get_db),
    usuario=Depends(_require_liquidaciones_write),
):
    liq = Liquidacion(
        proyecto_id=body.proyecto_id,
        generado_por_id=usuario.id,
        periodo=body.periodo,
        tipo_venta=body.tipo_venta,
        estado="iniciada",
        observaciones_resultados=body.observaciones_resultados,
    )
    db.add(liq)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una liquidación para este proyecto y período")
    db.refresh(liq)
    return {"id": liq.id, "msg": "Liquidación creada"}


# ── Resumen espejo del Panel Contable ──────────────────────────────────────────
# Debe ir ANTES de "/{id}" — Starlette matchea rutas en orden de registro, y
# "/{id}" (con id: int) intercepta cualquier segmento literal registrado después
# (ver bug preexistente en GET /resumen, que sufre lo mismo).

@router.get("/resumen-panel")
def resumen_liquidaciones_desde_panel(
    periodo: str = Query(..., description="YYYY-MM"),
    tipo: str = Query("preliquidacion", description="preliquidacion | oficial"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Resumen de Liquidaciones = espejo de lectura del Panel Contable del período.

    Fuente única: los tres tabs de Liquidaciones (Resumen, Proyectos,
    Inversionistas) se arman de aquí, así que cuadran siempre con el Panel.
    'valor a pagar' sale del grupo 'resultado' (o, si el ER no lo trae, de
    ingresos - comercializacion - costos - facturas). La tabla Liquidacion queda
    solo para el detalle operativo (mandatos/facturas/XM); por eso se incluye
    liquidacion_id por proyecto para poder navegar al detalle.
    """
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
        periodo_date = date(int(y), int(m), 1)
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    paneles = (
        db.query(PanelContable)
        .options(selectinload(PanelContable.lineas))
        .filter(PanelContable.periodo == periodo_norm, PanelContable.tipo == tipo)
        .order_by(PanelContable.id)
        .all()
    )

    proy_ids = [p.proyecto_id for p in paneles]

    # Nombre + tipo de cada proyecto (solo los del período, no toda la tabla).
    nombres: dict = {}
    tipos: dict = {}
    if proy_ids:
        for pid, nom, tp in (
            db.query(Proyecto.id, Proyecto.nombre_comercial, Proyecto.tipo_proyecto)
            .filter(Proyecto.id.in_(proy_ids))
            .all()
        ):
            nombres[pid] = nom
            tipos[pid] = tp.value if tp is not None else None

    # Liquidacion (detalle operativo) por proyecto+período → para navegar al detalle.
    liq_por_proyecto: dict = {}
    if proy_ids:
        for lid, pid in (
            db.query(Liquidacion.id, Liquidacion.proyecto_id)
            .filter(
                Liquidacion.proyecto_id.in_(proy_ids),
                Liquidacion.periodo == periodo_date,
                Liquidacion.deleted_at.is_(None),
            )
            .order_by(Liquidacion.id)
            .all()
        ):
            liq_por_proyecto.setdefault(pid, lid)  # el primero por proyecto

    # Cliente de cada proyecto_inversionista presente en las líneas (para pivotar
    # la vista Inversionistas por cliente en el frontend). Batch, sin N+1.
    pi_ids = {
        ln.proyecto_inversionista_id
        for p in paneles for ln in p.lineas
        if ln.proyecto_inversionista_id is not None
    }
    cliente_por_pi: dict = {}
    if pi_ids:
        for pi_id, cli_id, razon in (
            db.query(
                ProyectoInversionista.id,
                ProyectoInversionista.cliente_id,
                Cliente.razon_social_nombre,
            )
            .outerjoin(Cliente, Cliente.id == ProyectoInversionista.cliente_id)
            .filter(ProyectoInversionista.id.in_(pi_ids))
            .all()
        ):
            cliente_por_pi[pi_id] = {"cliente_id": cli_id, "cliente_nombre": razon}

    return _construir_resumen_panel(
        paneles, periodo_norm, tipo, nombres, tipos, liq_por_proyecto, cliente_por_pi
    )


@router.get("/resumen-panel-rango")
def resumen_panel_rango(
    periodo_desde: str = Query(..., description="YYYY-MM"),
    periodo_hasta: str = Query(..., description="YYYY-MM"),
    tipo: str = Query("preliquidacion", description="preliquidacion | oficial"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Como resumen-panel pero para un rango de meses. Devuelve un resumen-panel
    por período (para las gráficas de tendencia y los pivots multi-mes de las
    vistas Resumen e Inversionistas). Sigue siendo espejo del Panel Contable."""
    def _norm(p: str) -> str:
        y, m = p.strip().split("-")
        return f"{int(y):04d}-{int(m):02d}"

    try:
        desde = _norm(periodo_desde)
        hasta = _norm(periodo_hasta)
        dy, dm = desde.split("-")
        hy, hm = hasta.split("-")
        desde_date = date(int(dy), int(dm), 1)
        hasta_date = date(int(hy), int(hm), 1)
    except Exception:
        raise HTTPException(422, "Los períodos deben tener formato YYYY-MM")

    paneles = (
        db.query(PanelContable)
        .options(selectinload(PanelContable.lineas))
        .filter(
            PanelContable.periodo >= desde,
            PanelContable.periodo <= hasta,
            PanelContable.tipo == tipo,
        )
        .order_by(PanelContable.periodo, PanelContable.id)
        .all()
    )

    por_periodo: dict = {}
    for p in paneles:
        por_periodo.setdefault(p.periodo, []).append(p)

    proy_ids = {p.proyecto_id for p in paneles}
    nombres: dict = {}
    tipos: dict = {}
    if proy_ids:
        for pid, nom, tp in (
            db.query(Proyecto.id, Proyecto.nombre_comercial, Proyecto.tipo_proyecto)
            .filter(Proyecto.id.in_(proy_ids)).all()
        ):
            nombres[pid] = nom
            tipos[pid] = tp.value if tp is not None else None

    pi_ids = {
        ln.proyecto_inversionista_id
        for p in paneles for ln in p.lineas
        if ln.proyecto_inversionista_id is not None
    }
    cliente_por_pi: dict = {}
    if pi_ids:
        for pi_id, cli_id, razon in (
            db.query(
                ProyectoInversionista.id,
                ProyectoInversionista.cliente_id,
                Cliente.razon_social_nombre,
            )
            .outerjoin(Cliente, Cliente.id == ProyectoInversionista.cliente_id)
            .filter(ProyectoInversionista.id.in_(pi_ids)).all()
        ):
            cliente_por_pi[pi_id] = {"cliente_id": cli_id, "cliente_nombre": razon}

    # liquidacion_id por (proyecto, período) para navegar al detalle.
    liq_map: dict = {}
    if proy_ids:
        for lid, pid, per in (
            db.query(Liquidacion.id, Liquidacion.proyecto_id, Liquidacion.periodo)
            .filter(
                Liquidacion.proyecto_id.in_(proy_ids),
                Liquidacion.periodo >= desde_date,
                Liquidacion.periodo <= hasta_date,
                Liquidacion.deleted_at.is_(None),
            )
            .order_by(Liquidacion.id).all()
        ):
            key = (pid, per.strftime("%Y-%m")) if per else None
            if key and key not in liq_map:
                liq_map[key] = lid

    periodos_out = []
    for per in sorted(por_periodo.keys()):
        proys_del_periodo = {pp.proyecto_id for pp in por_periodo[per]}
        liq_por_proyecto = {pid: liq_map.get((pid, per)) for pid in proys_del_periodo}
        periodos_out.append(
            _construir_resumen_panel(
                por_periodo[per], per, tipo, nombres, tipos, liq_por_proyecto, cliente_por_pi
            )
        )

    return {"tipo": tipo, "periodos": periodos_out}


def _construir_resumen_panel(paneles, periodo_norm, tipo, nombres, tipos,
                             liq_por_proyecto, cliente_por_pi) -> dict:
    """Arma el resumen espejo a partir de paneles ya cargados y de los mapas de
    apoyo (nombres/tipos de proyecto, liquidacion_id por proyecto, cliente por
    proyecto_inversionista). Función pura: sin acceso a DB, testeable sola."""
    proyectos_out = []
    total_valor_a_pagar = 0.0
    total_ingresos = 0.0
    total_costos = 0.0

    for panel in paneles:
        inv_map: dict = {}
        for ln in sorted(panel.lineas, key=lambda x: x.orden):
            key = ln.proyecto_inversionista_id or f"_{ln.inversionista_nombre}"
            if key not in inv_map:
                cli = cliente_por_pi.get(ln.proyecto_inversionista_id) or {}
                inv_map[key] = {
                    "proyecto_inversionista_id": ln.proyecto_inversionista_id,
                    "cliente_id": cli.get("cliente_id"),
                    "cliente_nombre": cli.get("cliente_nombre") or ln.inversionista_nombre,
                    "nombre": ln.inversionista_nombre,
                    "porcentaje": float(ln.porcentaje) if ln.porcentaje is not None else None,
                    "grupos": {},
                    "conceptos": [],
                }
            valor = float(ln.valor_cop) if ln.valor_cop is not None else 0.0
            inv_map[key]["grupos"][ln.grupo] = inv_map[key]["grupos"].get(ln.grupo, 0.0) + valor
            inv_map[key]["conceptos"].append({
                "grupo": ln.grupo, "concepto": ln.concepto, "valor_cop": valor,
            })

        inversionistas_out = []
        proyecto_valor_a_pagar = 0.0
        proyecto_ingresos = 0.0
        proyecto_costos = 0.0
        for inv in inv_map.values():
            grupos = inv["grupos"]
            # El Panel guarda comercializacion/costos/facturas con signo NEGATIVO, así
            # que el valor a pagar es la SUMA de todas las líneas con su signo — idéntico
            # a utilidad(inv) del Panel Contable (PanelContableView.vue:625). Si existe un
            # grupo 'resultado' explícito, ese ya es el neto y no se re-suma.
            if "resultado" in grupos:
                valor_a_pagar = grupos["resultado"]
            else:
                valor_a_pagar = sum(grupos.values())
            inversionistas_out.append({
                "proyecto_inversionista_id": inv["proyecto_inversionista_id"],
                "cliente_id": inv["cliente_id"],
                "cliente_nombre": inv["cliente_nombre"],
                "nombre": inv["nombre"],
                "porcentaje": inv["porcentaje"],
                "valor_a_pagar": round(valor_a_pagar, 2),
                "grupos_totales": {g: round(v, 2) for g, v in grupos.items()},
                "conceptos": inv["conceptos"],
            })
            proyecto_valor_a_pagar += valor_a_pagar
            proyecto_ingresos += grupos.get("ingresos", 0.0)
            # Costos = todo lo que resta (comercializacion + costos + facturas), con signo.
            proyecto_costos += (
                grupos.get("comercializacion", 0.0)
                + grupos.get("costos", 0.0)
                + grupos.get("facturas", 0.0)
            )

        proyectos_out.append({
            "panel_id": panel.id,
            "proyecto_id": panel.proyecto_id,
            "proyecto": nombres.get(panel.proyecto_id, f"Proyecto {panel.proyecto_id}"),
            "tipo_proyecto": tipos.get(panel.proyecto_id),
            "liquidacion_id": liq_por_proyecto.get(panel.proyecto_id),
            "consecutivo_ingresos": panel.consecutivo_ingresos,
            "consecutivo_costos": panel.consecutivo_costos,
            "fecha_firma": panel.fecha_firma.isoformat() if panel.fecha_firma else None,
            "liquidar_ingresos": panel.liquidar_ingresos,
            "liquidar_costos": panel.liquidar_costos,
            "estado": "firmado" if panel.fecha_firma else "pendiente",
            "valor_a_pagar_total": round(proyecto_valor_a_pagar, 2),
            "ingresos_cop": round(proyecto_ingresos, 2),
            "costos_cop": round(proyecto_costos, 2),
            "inversionistas": inversionistas_out,
        })
        total_valor_a_pagar += proyecto_valor_a_pagar
        total_ingresos += proyecto_ingresos
        total_costos += proyecto_costos

    return {
        "periodo": periodo_norm,
        "tipo": tipo,
        "resumen": {
            "num_proyectos": len(proyectos_out),
            "valor_a_pagar_total": round(total_valor_a_pagar, 2),
            "ingresos_total_cop": round(total_ingresos, 2),
            "costos_total_cop": round(total_costos, 2),
            # costos ya viene con signo negativo → neto = ingresos + costos.
            "ingreso_neto_cop": round(total_ingresos + total_costos, 2),
        },
        "proyectos": proyectos_out,
    }


@router.get("/{id}")
def get_liquidacion(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        liq = db.query(Liquidacion).options(selectinload(Liquidacion.proyecto)).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
        if not liq:
            raise HTTPException(404, "Liquidación no encontrada")

        costos = db.query(LiquidacionCosto).filter(LiquidacionCosto.liquidacion_id == id).all()
        facturas = db.query(LiquidacionFactura).filter(LiquidacionFactura.liquidacion_id == id).all()
        mandatos = (
            db.query(LiquidacionMandato)
            .options(
                selectinload(LiquidacionMandato.lineas),
                selectinload(LiquidacionMandato.inversionista)
                    .selectinload(ProyectoInversionista.cliente),
            )
            .filter(LiquidacionMandato.liquidacion_id == id)
            .all()
        )

        try:
            xm_datos = db.query(LiquidacionXMDato).filter(LiquidacionXMDato.liquidacion_id == id).all()
        except Exception:
            db.rollback()
            xm_datos = []

        data = _serializar_liquidacion_base(liq)
        data["costos"] = [_serializar_costo(c) for c in costos]
        data["facturas"] = [_serializar_factura(f) for f in facturas]
        data["mandatos"] = [_serializar_mandato(m) for m in mandatos]
        data["xm_datos"] = [_serializar_xm_dato(x) for x in xm_datos]
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error in get_liquidacion %s: %s\n%s", id, exc, traceback.format_exc())
        raise HTTPException(500, f"Error interno: {exc}")


@router.patch("/{id}")
def update_liquidacion(
    id: int,
    body: LiquidacionUpdate,
    db: Session = Depends(get_db),
    _=Depends(_require_liquidaciones_write),
):
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(liq, field, value)
    db.commit()
    return {"msg": "Actualizada"}


class InformeLiquidacionUpdate(BaseModel):
    html_content: str | None = None


@router.get("/{id}/informe")
def get_informe_liquidacion(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Informe PDF editable de la liquidación (HTML embebido)."""
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    return {
        "id": liq.id,
        "html_content": liq.informe_html,
        "actualizado_en": liq.informe_actualizado_en.isoformat() if liq.informe_actualizado_en else None,
    }


@router.put("/{id}/informe")
def guardar_informe_liquidacion(
    id: int,
    body: InformeLiquidacionUpdate,
    db: Session = Depends(get_db),
    _=Depends(_require_liquidaciones_write),
):
    """Guarda (upsert) el HTML del informe PDF de la liquidación en la BD."""
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    liq.informe_html = body.html_content
    liq.informe_actualizado_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(liq)
    return {
        "msg": "Informe guardado",
        "actualizado_en": liq.informe_actualizado_en.isoformat() if liq.informe_actualizado_en else None,
    }


@router.delete("/{id}", status_code=204)
def delete_liquidacion(id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    liq.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/{id}/limpiar", status_code=204)
def limpiar_liquidacion(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(_require_liquidaciones_write),
):
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")

    mandatos = (
        db.query(LiquidacionMandato)
        .filter(LiquidacionMandato.liquidacion_id == id)
        .all()
    )
    for m in mandatos:
        db.query(LiquidacionMandatoLinea).filter(
            LiquidacionMandatoLinea.mandato_id == m.id
        ).delete(synchronize_session=False)
        db.delete(m)

    db.query(LiquidacionCosto).filter(
        LiquidacionCosto.liquidacion_id == id
    ).delete(synchronize_session=False)

    db.query(LiquidacionFactura).filter(
        LiquidacionFactura.liquidacion_id == id
    ).delete(synchronize_session=False)

    try:
        db.query(LiquidacionXMDato).filter(
            LiquidacionXMDato.liquidacion_id == id
        ).delete(synchronize_session=False)
    except Exception:
        db.rollback()

    db.commit()


# ── Costos ─────────────────────────────────────────────────────────────────────

@router.post("/{id}/costos", status_code=201)
def add_costo(id: int, body: CostoCreate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    if not db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first():
        raise HTTPException(404, "Liquidación no encontrada")
    costo = LiquidacionCosto(liquidacion_id=id, **body.model_dump())
    db.add(costo)
    db.commit()
    db.refresh(costo)
    return _serializar_costo(costo)


@router.patch("/{id}/costos/{costo_id}")
def update_costo(id: int, costo_id: int, body: CostoUpdate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    costo = db.query(LiquidacionCosto).filter(
        LiquidacionCosto.id == costo_id, LiquidacionCosto.liquidacion_id == id
    ).first()
    if not costo:
        raise HTTPException(404, "Costo no encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(costo, field, value)
    db.commit()
    return _serializar_costo(costo)


@router.delete("/{id}/costos/{costo_id}", status_code=204)
def delete_costo(id: int, costo_id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    costo = db.query(LiquidacionCosto).filter(
        LiquidacionCosto.id == costo_id, LiquidacionCosto.liquidacion_id == id
    ).first()
    if not costo:
        raise HTTPException(404, "Costo no encontrado")
    db.delete(costo)
    db.commit()


# ── Mandatos ───────────────────────────────────────────────────────────────────

@router.post("/{id}/mandatos", status_code=201)
def add_mandato(id: int, body: MandatoCreate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    if not db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first():
        raise HTTPException(404, "Liquidación no encontrada")
    mandato = LiquidacionMandato(liquidacion_id=id, **body.model_dump())
    db.add(mandato)
    db.commit()
    db.refresh(mandato)
    return {"id": mandato.id, "msg": "Mandato creado"}


@router.patch("/{id}/mandatos/{mandato_id}")
def update_mandato(id: int, mandato_id: int, body: MandatoUpdate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    mandato = db.query(LiquidacionMandato).filter(
        LiquidacionMandato.id == mandato_id, LiquidacionMandato.liquidacion_id == id
    ).first()
    if not mandato:
        raise HTTPException(404, "Mandato no encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(mandato, field, value)
    db.commit()
    return {"msg": "Mandato actualizado"}


@router.delete("/{id}/mandatos/{mandato_id}", status_code=204)
def delete_mandato(id: int, mandato_id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    mandato = db.query(LiquidacionMandato).filter(
        LiquidacionMandato.id == mandato_id, LiquidacionMandato.liquidacion_id == id
    ).first()
    if not mandato:
        raise HTTPException(404, "Mandato no encontrado")
    # Delete child lineas first to avoid FK constraint violation
    db.query(LiquidacionMandatoLinea).filter(
        LiquidacionMandatoLinea.mandato_id == mandato_id
    ).delete(synchronize_session=False)
    db.delete(mandato)
    db.commit()


# ── Líneas de mandato ──────────────────────────────────────────────────────────

@router.post("/{id}/mandatos/{mandato_id}/lineas", status_code=201)
def add_linea(id: int, mandato_id: int, body: LineaCreate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    mandato = db.query(LiquidacionMandato).filter(
        LiquidacionMandato.id == mandato_id, LiquidacionMandato.liquidacion_id == id
    ).first()
    if not mandato:
        raise HTTPException(404, "Mandato no encontrado")
    linea = LiquidacionMandatoLinea(mandato_id=mandato_id, **body.model_dump())
    db.add(linea)
    db.commit()
    db.refresh(linea)
    return _serializar_linea(linea)


@router.patch("/{id}/mandatos/{mandato_id}/lineas/{linea_id}")
def update_linea(id: int, mandato_id: int, linea_id: int, body: LineaUpdate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    linea = db.query(LiquidacionMandatoLinea).filter(
        LiquidacionMandatoLinea.id == linea_id,
        LiquidacionMandatoLinea.mandato_id == mandato_id,
    ).first()
    if not linea:
        raise HTTPException(404, "Línea no encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(linea, field, value)
    db.commit()
    return _serializar_linea(linea)


@router.delete("/{id}/mandatos/{mandato_id}/lineas/{linea_id}", status_code=204)
def delete_linea(id: int, mandato_id: int, linea_id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    linea = db.query(LiquidacionMandatoLinea).filter(
        LiquidacionMandatoLinea.id == linea_id,
        LiquidacionMandatoLinea.mandato_id == mandato_id,
    ).first()
    if not linea:
        raise HTTPException(404, "Línea no encontrada")
    db.delete(linea)
    db.commit()


# ── Facturas de servicio ───────────────────────────────────────────────────────

@router.post("/{id}/facturas", status_code=201)
def add_factura(id: int, body: FacturaCreate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    if not db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first():
        raise HTTPException(404, "Liquidación no encontrada")
    factura = LiquidacionFactura(liquidacion_id=id, **body.model_dump())
    db.add(factura)
    db.commit()
    db.refresh(factura)
    return _serializar_factura(factura)


@router.patch("/{id}/facturas/{factura_id}")
def update_factura(id: int, factura_id: int, body: FacturaUpdate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    factura = db.query(LiquidacionFactura).filter(
        LiquidacionFactura.id == factura_id, LiquidacionFactura.liquidacion_id == id
    ).first()
    if not factura:
        raise HTTPException(404, "Factura no encontrada")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(factura, field, value)
    db.commit()
    return _serializar_factura(factura)


@router.delete("/{id}/facturas/{factura_id}", status_code=204)
def delete_factura(id: int, factura_id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    factura = db.query(LiquidacionFactura).filter(
        LiquidacionFactura.id == factura_id, LiquidacionFactura.liquidacion_id == id
    ).first()
    if not factura:
        raise HTTPException(404, "Factura no encontrada")
    db.delete(factura)
    db.commit()


# ── Catálogos de enums ─────────────────────────────────────────────────────────

@router.get("/catalogos/tipos")
def catalogos(_=Depends(get_current_user)):
    return {
        "tipo_costo": [e.value for e in TipoCostoEnum],
        "tipo_mandato": [e.value for e in TipoMandatoEnum],
        "tipo_linea_mandato": [e.value for e in TipoLineaMandatoEnum],
        "tipo_factura_servicio": [e.value for e in TipoFacturaServicioEnum],
        "estado_liquidacion": [e.value for e in EstadoLiquidacionEnum],
        "estado_mandato": [e.value for e in EstadoMandatoEnum],
        "estado_factura": [e.value for e in EstadoFacturaEnum],
    }


# ── XM Data (Datos de Mercado XM) ───────────────────────────────────────────

@router.post("/{id}/xm-datos", status_code=201)
def add_xm_dato(id: int, body: XMDatoCreate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    _get_liq_or_404(id, db)
    dato = LiquidacionXMDato(
        liquidacion_id=id,
        frontera_id=body.frontera_id,
        tipo_venta=body.tipo_venta,
        energia_kwh=body.energia_kwh,
        tarifa_aplicada_kwh=body.tarifa_aplicada_kwh,
        valor_bruto_cop=body.valor_bruto_cop,
        referencia_factura_xm=body.referencia_factura_xm,
        fecha_factura_xm=body.fecha_factura_xm,
    )
    db.add(dato)
    db.commit()
    db.refresh(dato)
    return _serializar_xm_dato(dato)


@router.patch("/{id}/xm-datos/{dato_id}")
def update_xm_dato(id: int, dato_id: int, body: XMDatoUpdate, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    dato = db.query(LiquidacionXMDato).filter(
        LiquidacionXMDato.id == dato_id,
        LiquidacionXMDato.liquidacion_id == id,
    ).first()
    if not dato:
        raise HTTPException(404, "Dato XM no encontrado")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(dato, field, val)
    db.commit()
    db.refresh(dato)
    return _serializar_xm_dato(dato)


@router.delete("/{id}/xm-datos/{dato_id}", status_code=204)
def delete_xm_dato(id: int, dato_id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    dato = db.query(LiquidacionXMDato).filter(
        LiquidacionXMDato.id == dato_id,
        LiquidacionXMDato.liquidacion_id == id,
    ).first()
    if not dato:
        raise HTTPException(404, "Dato XM no encontrado")
    db.delete(dato)
    db.commit()


@router.post("/{id}/xm-datos/auto-populate")
def auto_populate_xm_datos(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(_require_liquidaciones_write),
):
    """
    Auto-populate XM data from generacion_diaria + precios_bolsa for this liquidación's
    proyecto and periodo. Bridges cumplimiento → liquidaciones.
    """
    liq = _get_liq_or_404(id, db)
    year = liq.periodo.year
    month = liq.periodo.month

    existing = db.query(LiquidacionXMDato).filter(LiquidacionXMDato.liquidacion_id == id).count()
    if existing > 0:
        raise HTTPException(
            409,
            f"La liquidación ya tiene {existing} datos XM. Elimínelos primero si desea re-poblar.",
        )

    gen_row = db.execute(text("""
        SELECT SUM(kwh_real) as total_kwh
        FROM generacion_diaria
        WHERE proyecto_id = :pid
          AND EXTRACT(YEAR FROM fecha) = :year
          AND EXTRACT(MONTH FROM fecha) = :month
          AND kwh_real IS NOT NULL
    """), {"pid": liq.proyecto_id, "year": year, "month": month}).first()

    total_kwh = float(gen_row.total_kwh or 0) if gen_row else 0.0
    if total_kwh <= 0:
        return {"msg": "Sin generación registrada para este período", "xm_datos": []}

    tarifa = 0.0
    tarifa_source = "bolsa"

    # For PPA tipo_venta, look up the contracted tariff first
    if liq.tipo_venta == "ppa":
        ppa_tarifa_row = (
            db.query(PPATarifa.tarifa)
            .join(PPAContrato, PPATarifa.contrato_id == PPAContrato.id)
            .join(
                ppa_contrato_proyectos_table,
                ppa_contrato_proyectos_table.c.contrato_id == PPAContrato.id,
            )
            .filter(
                ppa_contrato_proyectos_table.c.proyecto_id == liq.proyecto_id,
                PPATarifa.año == year,
                PPATarifa.mes == month,
                PPATarifa.tarifa.isnot(None),
                PPAContrato.deleted_at.is_(None),
            )
            .first()
        )
        if ppa_tarifa_row and ppa_tarifa_row.tarifa:
            tarifa = float(ppa_tarifa_row.tarifa)
            tarifa_source = "ppa"

    # Fall back to bolsa price average if no PPA tariff found or tipo_venta is not PPA
    if tarifa == 0.0:
        precio_row = db.execute(text("""
            SELECT AVG(precio_promedio_kwh) as tarifa_avg
            FROM precios_bolsa_diario
            WHERE EXTRACT(YEAR FROM fecha) = :year
              AND EXTRACT(MONTH FROM fecha) = :month
              AND precio_promedio_kwh IS NOT NULL
        """), {"year": year, "month": month}).first()

        tarifa = float(precio_row.tarifa_avg) if precio_row and precio_row.tarifa_avg else 0.0
        tarifa_source = "bolsa"

    frontera_row = db.execute(text("""
        SELECT f.id
        FROM fronteras f
        WHERE f.proyecto_id = :pid
          AND f.estado = 'activa'
        LIMIT 1
    """), {"pid": liq.proyecto_id}).first()
    frontera_id = frontera_row.id if frontera_row else None

    tipo_venta = liq.tipo_venta or "bolsa"
    valor_bruto = round(total_kwh * tarifa, 2)

    dato = LiquidacionXMDato(
        liquidacion_id=id,
        frontera_id=frontera_id,
        tipo_venta=tipo_venta,
        energia_kwh=round(total_kwh, 3),
        tarifa_aplicada_kwh=round(tarifa, 6),
        valor_bruto_cop=valor_bruto,
    )
    db.add(dato)
    db.commit()
    db.refresh(dato)

    if liq.ingresos_energia_cop is None:
        liq.ingresos_energia_cop = valor_bruto
        liq.estado = "xm_procesado"
        db.commit()

    return {
        "msg": f"Datos XM poblados: {total_kwh:.1f} kWh × ${tarifa:.2f} ({tarifa_source}) = ${valor_bruto:,.0f} COP",
        "xm_datos": [_serializar_xm_dato(dato)],
    }


# ── Carga masiva desde Excel ───────────────────────────────────────────────────

@router.post("/cargar-excel")
async def cargar_excel(
    file: UploadFile = File(...),
    hoja: str = Form(...),
    periodo: str = Form(...),
    limpiar: str = Form("false"),
    dry_run: str = Form("false"),
    tipo_venta: str = Form("ppa"),
    db: Session = Depends(get_db),
    current: Usuario = Depends(_require_liquidaciones_write),
):
    """
    Carga un archivo Excel de panel de seguimiento contable.
    periodo: YYYY-MM  (ej: 2026-05)
    tipo_venta: "ppa" (panel de seguimiento) o "autoconsumo" (estructura SUNO).
    dry_run=true: retorna preview sin escribir en DB.
    limpiar=true: borra mandatos/costos/facturas existentes antes de reimportar.
    """
    import tempfile, os
    from app.utils.liquidaciones_loader import leer_hoja, leer_hoja_autoconsumo, cargar_desde_db

    limpiar_bool = limpiar.lower() in ("true", "1", "yes", "on")
    dry_run_bool = dry_run.lower() in ("true", "1", "yes", "on")
    tipo_venta = (tipo_venta or "ppa").strip().lower()
    if tipo_venta not in ("ppa", "autoconsumo"):
        raise HTTPException(422, "tipo_venta debe ser 'ppa' o 'autoconsumo'")

    # Validar período
    try:
        y, m = periodo.strip().split("-")
        periodo_date = f"{int(y):04d}-{int(m):02d}-01"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    # Guardar en tempfile
    suffix = ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        contents = await file.read()
        tmp.write(contents)
        tmp.flush()
        tmp.close()

        if tipo_venta == "autoconsumo":
            filas, er_map = leer_hoja_autoconsumo(tmp.name, hoja)
        else:
            filas, er_map = leer_hoja(tmp.name, hoja)
        resultado = cargar_desde_db(
            db=db,
            filas=filas,
            er_map=er_map,
            periodo_date=periodo_date,
            limpiar=limpiar_bool,
            dry_run=dry_run_bool,
            usuario_id=current.id,
            tipo_venta=tipo_venta,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.exception("Error procesando Excel de liquidaciones")
        raise HTTPException(500, f"Error procesando el archivo: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return resultado
