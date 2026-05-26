import logging
import traceback
from datetime import date
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
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
        "valor_cop": float(c.valor_cop),
        "created_at": c.created_at.isoformat(),
    }


def _serializar_linea(l: LiquidacionMandatoLinea) -> dict:
    return {
        "id": l.id,
        "tipo_linea": str(l.tipo_linea) if l.tipo_linea is not None else None,
        "concepto": l.concepto,
        "valor_cop": float(l.valor_cop),
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


@router.get("/{id}")
def get_liquidacion(id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
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


@router.delete("/{id}", status_code=204)
def delete_liquidacion(id: int, db: Session = Depends(get_db), _=Depends(_require_liquidaciones_write)):
    liq = db.query(Liquidacion).filter(Liquidacion.id == id, Liquidacion.deleted_at.is_(None)).first()
    if not liq:
        raise HTTPException(404, "Liquidación no encontrada")
    liq.deleted_at = func.now()
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


# ── Vista Por Proyecto ─────────────────────────────────────────────────────────

@router.get("/vistas/por-proyecto")
def vista_por_proyecto(
    periodo_desde: date | None = None,
    periodo_hasta: date | None = None,
    proyecto_id: int | None = None,
    estado: str | None = None,
    tipo_proyecto: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    try:
        proy_q = db.query(Proyecto)
        if proyecto_id:
            proy_q = proy_q.filter(Proyecto.id == proyecto_id)
        if tipo_proyecto:
            proy_q = proy_q.filter(Proyecto.tipo_proyecto == tipo_proyecto)
        todos_proyectos = proy_q.order_by(Proyecto.nombre_comercial).all()
        proy_ids = [p.id for p in todos_proyectos]

        inv_registrados_map: dict[int, list] = {pid: [] for pid in proy_ids}
        if proy_ids:
            for pi in (
                db.query(ProyectoInversionista)
                .options(selectinload(ProyectoInversionista.cliente))
                .filter(ProyectoInversionista.proyecto_id.in_(proy_ids))
                .all()
            ):
                inv_registrados_map[pi.proyecto_id].append({
                    "proyecto_inversionista_id": pi.id,
                    "cliente_id": pi.cliente_id,
                    "inversionista_nombre": pi.cliente.razon_social_nombre if pi.cliente else "—",
                    "porcentaje_participacion": float(pi.porcentaje_participacion or 0) if pi.porcentaje_participacion is not None else None,
                    "es_patrimonio_autonomo": pi.es_patrimonio_autonomo,
                })

        liq_q = (
            db.query(Liquidacion)
            .options(selectinload(Liquidacion.proyecto))
            .filter(Liquidacion.proyecto_id.in_(proy_ids), Liquidacion.deleted_at.is_(None))
        )
        if periodo_desde:
            liq_q = liq_q.filter(Liquidacion.periodo >= periodo_desde)
        if periodo_hasta:
            liq_q = liq_q.filter(Liquidacion.periodo <= periodo_hasta)
        if estado:
            liq_q = liq_q.filter(Liquidacion.estado == estado)
        liquidaciones = liq_q.order_by(Liquidacion.periodo.desc()).all()
        liq_ids = [liq.id for liq in liquidaciones]

        costos_map: dict[int, list] = {lid: [] for lid in liq_ids}
        facturas_map: dict[int, list] = {lid: [] for lid in liq_ids}
        mandatos_map: dict[int, list] = {lid: [] for lid in liq_ids}

        if liq_ids:
            for c in db.query(LiquidacionCosto).filter(LiquidacionCosto.liquidacion_id.in_(liq_ids)).all():
                costos_map[c.liquidacion_id].append(c)
            for f in db.query(LiquidacionFactura).filter(LiquidacionFactura.liquidacion_id.in_(liq_ids)).all():
                facturas_map[f.liquidacion_id].append(f)
            for m in (
                db.query(LiquidacionMandato)
                .options(
                    selectinload(LiquidacionMandato.lineas),
                    selectinload(LiquidacionMandato.inversionista).selectinload(ProyectoInversionista.cliente),
                )
                .filter(LiquidacionMandato.liquidacion_id.in_(liq_ids))
                .all()
            ):
                mandatos_map[m.liquidacion_id].append(m)

        liq_por_proyecto: dict[int, list] = {p.id: [] for p in todos_proyectos}
        for liq in liquidaciones:
            if liq.proyecto_id not in liq_por_proyecto:
                continue
            liq_mandatos = mandatos_map.get(liq.id, [])
            mandatos_ingresos = [m for m in liq_mandatos if m.tipo == "ingresos" and m.inversionista_id is not None]
            mandatos_costos   = [m for m in liq_mandatos if m.tipo == "costos"   and m.inversionista_id is not None]
            mandatos_total_ing = [m for m in liq_mandatos if m.tipo == "ingresos" and m.inversionista_id is None]
            mandatos_total_cos = [m for m in liq_mandatos if m.tipo == "costos"   and m.inversionista_id is None]

            total_ingresos = sum(float(m.total_ingresos_cop or 0) for m in mandatos_ingresos)
            total_costos = sum(float(m.total_costos_cop or 0) for m in mandatos_costos)
            total_facturas = sum(float(f.valor_cop) for f in facturas_map.get(liq.id, []))

            inversionistas_ids = {m.inversionista_id for m in liq_mandatos if m.inversionista_id}
            inversionistas_rows = []
            for inv_id in inversionistas_ids:
                inv_m_ing = [m for m in mandatos_ingresos if m.inversionista_id == inv_id]
                inv_m_cos = [m for m in mandatos_costos if m.inversionista_id == inv_id]
                inv_obj = (inv_m_ing[0] if inv_m_ing else (inv_m_cos[0] if inv_m_cos else None))
                inv_obj = inv_obj.inversionista if inv_obj else None
                inversionistas_rows.append({
                    "inversionista_id": inv_id,
                    "inversionista_nombre": inv_obj.cliente.razon_social_nombre if (inv_obj and inv_obj.cliente) else "—",
                    "porcentaje_participacion": float(inv_obj.porcentaje_participacion or 0) if inv_obj else None,
                    "es_patrimonio_autonomo": inv_obj.es_patrimonio_autonomo if inv_obj else False,
                    "mandatos_ingresos": [_serializar_mandato(m) for m in inv_m_ing],
                    "mandatos_costos": [_serializar_mandato(m) for m in inv_m_cos],
                })

            liq_por_proyecto[liq.proyecto_id].append({
                "liquidacion_id": liq.id,
                "periodo": liq.periodo.isoformat(),
                "estado": liq.estado,
                "tipo_venta": liq.tipo_venta,
                "comprobante_contable_ref": liq.comprobante_contable_ref,
                "consecutivo_inicial_ingresos": liq.consecutivo_inicial_ingresos,
                "consecutivo_inicial_costos": liq.consecutivo_inicial_costos,
                "estado_resultados_url": liq.estado_resultados_url,
                "resumen": {
                    "total_ingresos_cop": total_ingresos,
                    "total_costos_cop": total_costos,
                    "total_facturas_cop": total_facturas,
                    "ingreso_neto_cop": float(liq.ingreso_neto_cop or 0),
                },
                "costos_proyecto": [_serializar_costo(c) for c in costos_map.get(liq.id, [])],
                "facturas_servicio": [_serializar_factura(f) for f in facturas_map.get(liq.id, [])],
                "mandatos_total_ingresos": [_serializar_mandato(m) for m in mandatos_total_ing],
                "mandatos_total_costos":   [_serializar_mandato(m) for m in mandatos_total_cos],
                "inversionistas": inversionistas_rows,
            })

        result = []
        for proy in todos_proyectos:
            result.append({
                "proyecto_id": proy.id,
                "proyecto_nombre": proy.nombre_comercial,
                "estado": proy.estado.value if proy.estado else None,
                "tipo_proyecto": proy.tipo_proyecto,
                "inversionistas_registrados": inv_registrados_map.get(proy.id, []),
                "liquidaciones": liq_por_proyecto.get(proy.id, []),
            })
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error in vista_por_proyecto: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"Error interno: {exc}")


# ── Vista Por Inversionista ────────────────────────────────────────────────────

@router.get("/vistas/por-inversionista")
def vista_por_inversionista(
    periodo_desde: date | None = None,
    periodo_hasta: date | None = None,
    cliente_id: int | None = None,
    estado: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Retorna TODOS los inversionistas (clientes con participaciones) con sus proyectos.
    Las liquidaciones se filtran por período y estado si se proporcionan.
    """
    pi_q = (
        db.query(ProyectoInversionista)
        .options(
            selectinload(ProyectoInversionista.cliente),
            selectinload(ProyectoInversionista.proyecto),
        )
    )
    if cliente_id:
        pi_q = pi_q.filter(ProyectoInversionista.cliente_id == cliente_id)
    all_pi = pi_q.all()

    proy_ids = list({pi.proyecto_id for pi in all_pi})

    liq_por_proyecto: dict[int, list] = {pid: [] for pid in proy_ids}
    if proy_ids:
        liq_q = (
            db.query(Liquidacion)
            .options(
                selectinload(Liquidacion.mandatos)
                    .selectinload(LiquidacionMandato.lineas),
            )
            .filter(Liquidacion.proyecto_id.in_(proy_ids), Liquidacion.deleted_at.is_(None))
        )
        if periodo_desde:
            liq_q = liq_q.filter(Liquidacion.periodo >= periodo_desde)
        if periodo_hasta:
            liq_q = liq_q.filter(Liquidacion.periodo <= periodo_hasta)
        if estado:
            liq_q = liq_q.filter(Liquidacion.estado == estado)
        for liq in liq_q.order_by(Liquidacion.periodo.desc()).all():
            if liq.proyecto_id in liq_por_proyecto:
                # Calcular ingreso neto desde mandatos Total (inversionista_id null)
                mandatos_ing = [
                    m for m in liq.mandatos
                    if m.tipo.value == "ingresos" and m.inversionista_id is None
                ]
                # Si no hay mandato Total, usar mandatos de inversionistas
                if not mandatos_ing:
                    mandatos_ing = [m for m in liq.mandatos if m.tipo.value == "ingresos"]
                valor_neto = sum(float(m.valor_neto_cop or 0) for m in mandatos_ing)
                ingreso_bruto = sum(
                    float(l.valor_cop)
                    for m in mandatos_ing
                    for l in m.lineas
                    if l.tipo_linea is not None
                    and l.tipo_linea.value in ("ingreso_bruto", "despacho", "ventas_en_bolsa")
                )
                mandatos_cos = [m for m in liq.mandatos if m.tipo.value == "costos"]
                # total_ingresos: suma de lineas ingreso_bruto/despacho/ventas (ya calculado)
                total_ingresos_cop = ingreso_bruto
                # total_facturas: deducción Unergy = bruto - valor_neto ingresos
                #   incluye ajuste_comercializacion, ajuste_xm, CGM, etc.
                total_facturas_cop = max(0.0, ingreso_bruto - valor_neto)
                # total_costos: valor_neto del mandato costos; fallback a suma de lineas
                total_costos_cop = 0.0
                for m in mandatos_cos:
                    if m.valor_neto_cop is not None:
                        total_costos_cop += float(m.valor_neto_cop)
                    else:
                        total_costos_cop += sum(float(l.valor_cop or 0) for l in m.lineas)
                liq_por_proyecto[liq.proyecto_id].append({
                    "liquidacion_id":   liq.id,
                    "periodo":          liq.periodo.isoformat(),
                    "estado":           liq.estado,
                    "tipo_venta":       liq.tipo_venta,
                    "ingreso_neto_cop":   float(liq.ingreso_neto_cop or valor_neto or ingreso_bruto or 0),
                    "total_ingresos_cop": total_ingresos_cop,
                    "total_costos_cop":   total_costos_cop,
                    "total_facturas_cop": total_facturas_cop,
                })

    clientes: dict[int, dict] = {}
    for pi in all_pi:
        cid = pi.cliente_id
        if cid not in clientes:
            clientes[cid] = {
                "cliente_id": cid,
                "cliente_nombre": pi.cliente.razon_social_nombre if pi.cliente else str(cid),
                "proyectos": [],
            }
        clientes[cid]["proyectos"].append({
            "proyecto_id": pi.proyecto_id,
            "proyecto_nombre": pi.proyecto.nombre_comercial if pi.proyecto else str(pi.proyecto_id),
            "proyecto_inversionista_id": pi.id,
            "porcentaje_participacion": float(pi.porcentaje_participacion or 0) if pi.porcentaje_participacion is not None else None,
            "es_patrimonio_autonomo": pi.es_patrimonio_autonomo,
            "liquidaciones": liq_por_proyecto.get(pi.proyecto_id, []),
        })

    return list(clientes.values())


# ── Resumen mensual ──────────────────────────────────────────────────────────

@router.get("/resumen")
def resumen_liquidaciones(
    year: int = Query(..., ge=2020, le=2050),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Summary of settlement status for a given month."""
    periodo = date(year, month, 1)

    liqs = (
        db.query(Liquidacion)
        .options(selectinload(Liquidacion.proyecto))
        .filter(Liquidacion.periodo == periodo, Liquidacion.deleted_at.is_(None))
        .all()
    )

    by_estado = {}
    total_ingresos = 0.0
    total_costos_op = 0.0
    for liq in liqs:
        estado = liq.estado or "iniciada"
        by_estado[estado] = by_estado.get(estado, 0) + 1
        if liq.ingresos_energia_cop:
            total_ingresos += float(liq.ingresos_energia_cop)
        if liq.costos_operativos_cop:
            total_costos_op += float(liq.costos_operativos_cop)

    proyectos_operacion = (
        db.query(func.count(Proyecto.id))
        .filter(Proyecto.estado == "en_operacion")
        .scalar() or 0
    )

    xm_datos_count = 0
    if liqs:
        liq_ids = [l.id for l in liqs]
        try:
            xm_datos_count = (
                db.query(func.count(LiquidacionXMDato.id))
                .filter(LiquidacionXMDato.liquidacion_id.in_(liq_ids))
                .scalar() or 0
            )
        except Exception:
            db.rollback()

    return {
        "periodo": periodo.isoformat(),
        "liquidaciones_total": len(liqs),
        "proyectos_operacion": proyectos_operacion,
        "proyectos_sin_liquidacion": proyectos_operacion - len(liqs),
        "por_estado": by_estado,
        "total_ingresos_energia_cop": round(total_ingresos, 0),
        "total_costos_operativos_cop": round(total_costos_op, 0),
        "xm_datos_registrados": xm_datos_count,
        "liquidaciones": [
            {
                "id": l.id,
                "proyecto_nombre": l.proyecto.nombre_comercial if l.proyecto else str(l.proyecto_id),
                "estado": l.estado,
                "tipo_venta": l.tipo_venta,
                "ingresos_energia_cop": float(l.ingresos_energia_cop or 0),
                "ingreso_neto_cop": float(l.ingreso_neto_cop or 0),
            }
            for l in liqs
        ],
    }


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
