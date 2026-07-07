"""Orquestador de la automatización de liquidación XM.

Al aprobarse un informe operativo, este servicio correlaciona:
  - Generación diaria del/los proyecto(s) del informe (``generacion_diaria``).
  - Precio de bolsa del MEM/XM para el período (``mem_ingestion_service``).
y produce filas ``LiquidacionXMIngesta`` (energía * precio = valor liquidado).

La lógica de cálculo vive en ``calcular_ingesta`` (pura, sin DB ni red) para que
sea fácil de testear; ``run_liquidacion_proceso`` hace el I/O (query de
generación, llamada al MEM, escritura transaccional e idempotente por informe).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crud import crud_liquidaciones
from app.models.generacion import GeneracionDiaria
from app.models.informes import InformeGuardado
from app.schemas.liquidaciones import LiquidacionIngestaResumen, LiquidacionXMIngestaCreate
from app.schemas.mem import PrecioBolsaDia
from app.services import mem_ingestion_service

logger = logging.getLogger(__name__)

FUENTE_DATOS = "generacion_diaria+mem_bolsa"

# Firma inyectable para traer precios de bolsa (permite testear sin red).
PreciosFn = Callable[[date, date], list[PrecioBolsaDia]]


# ── Núcleo puro (sin DB / sin red) ───────────────────────────────────────────

def calcular_ingesta(
    informe_id: int,
    generacion: Iterable[tuple[int, date, Optional[float]]],
    precios_por_fecha: dict[date, float],
    *,
    contrato_por_proyecto: Optional[dict[int, int]] = None,
) -> list[LiquidacionXMIngestaCreate]:
    """Combina generación diaria y precio de bolsa en filas de liquidación.

    - ``generacion``: iterable de (proyecto_id, fecha, energia_kwh). Filas con
      energía None se omiten (no hay nada que liquidar).
    - ``precios_por_fecha``: COP/kWh por fecha. Si falta la fecha, la fila queda
      con estado ``sin_precio`` y ``valor_liquidado_cop`` None.
    - ``contrato_por_proyecto``: mapa opcional proyecto_id → ppa_contrato_id.
    """
    contrato_por_proyecto = contrato_por_proyecto or {}
    filas: list[LiquidacionXMIngestaCreate] = []
    for proyecto_id, fecha, energia in generacion:
        if energia is None:
            continue
        energia_f = float(energia)
        precio = precios_por_fecha.get(fecha)
        if precio is not None:
            valor = round(energia_f * float(precio), 4)
            estado = "procesado"
        else:
            valor = None
            estado = "sin_precio"
        filas.append(
            LiquidacionXMIngestaCreate(
                informe_id=informe_id,
                proyecto_id=proyecto_id,
                ppa_contrato_id=contrato_por_proyecto.get(proyecto_id),
                fecha=fecha,
                hora=None,  # granularidad diaria (la fuente actual no trae hora)
                energia_generada_kwh=energia_f,
                precio_bolsa_cop_kwh=float(precio) if precio is not None else None,
                valor_liquidado_cop=valor,
                fuente_datos=FUENTE_DATOS,
                estado_proceso=estado,
                datos_adicionales=None,
            )
        )
    return filas


# ── Resolución de proyectos y período del informe ────────────────────────────

def _sub_projects_del_informe(inf: InformeGuardado) -> list[str]:
    """sub_projects que cubre el informe: el propio y, si es portafolio, los miembros."""
    subs: list[str] = []
    if inf.sub_project:
        subs.append(inf.sub_project)
    if inf.tipo == "port":
        for m in (inf.miembros or []):
            if isinstance(m, dict) and m.get("sub_project"):
                subs.append(m["sub_project"])
    # dedup preservando orden
    vistos: set[str] = set()
    return [s for s in subs if not (s in vistos or vistos.add(s))]


def _resolver_proyecto_ids(db: Session, inf: InformeGuardado) -> list[int]:
    """Resuelve los proyecto_id del informe (mismo criterio que app/api/v1/informes.py)."""
    ids: list[int] = []
    for sp in _sub_projects_del_informe(inf):
        row = db.execute(
            text(
                """
                SELECT p.id FROM proyectos p
                WHERE p.sub_project = :sp
                   OR p.nombre_comercial = :sp
                   OR p.alias_monitoreo ILIKE :sp_like
                LIMIT 1
                """
            ),
            {"sp": sp, "sp_like": f"%{sp}%"},
        ).fetchone()
        if row and row[0] not in ids:
            ids.append(row[0])
    return ids


def _parse_periodo(inf: InformeGuardado) -> tuple[Optional[date], Optional[date]]:
    def _p(s: Optional[str]) -> Optional[date]:
        if not s:
            return None
        try:
            y, m, d = s[:10].split("-")
            return date(int(y), int(m), int(d))
        except (ValueError, AttributeError):
            return None
    return _p(inf.periodo_desde), _p(inf.periodo_hasta)


def _precios_a_dict(precios: list[PrecioBolsaDia]) -> dict[date, float]:
    return {p.fecha: p.precio_cop_kwh for p in precios}


# ── Proceso completo (I/O) ───────────────────────────────────────────────────

def run_liquidacion_proceso(
    db: Session,
    informe_id: int,
    *,
    precios_fn: Optional[PreciosFn] = None,
) -> LiquidacionIngestaResumen:
    """Ejecuta la liquidación XM para un informe. Idempotente por informe.

    Escribe en una sola transacción: borra las filas previas del informe, inserta
    las nuevas y actualiza ``informe.liquidacion_status``. Ante cualquier fallo
    revierte los datos y deja el informe en estado ``ERROR``.
    """
    precios_fn = precios_fn or mem_ingestion_service.get_precios_bolsa

    inf = db.get(InformeGuardado, informe_id)
    if inf is None:
        logger.warning("Liquidación: informe %s no existe", informe_id)
        return LiquidacionIngestaResumen(
            informe_id=informe_id, liquidacion_status="ERROR",
            error="Informe no encontrado",
        )

    try:
        inf.liquidacion_status = "EN_PROCESO"
        db.flush()

        proyecto_ids = _resolver_proyecto_ids(db, inf)
        desde, hasta = _parse_periodo(inf)
        resumen = LiquidacionIngestaResumen(
            informe_id=informe_id, liquidacion_status="EN_PROCESO",
            proyectos=proyecto_ids, fecha_desde=desde, fecha_hasta=hasta,
        )

        if not proyecto_ids or desde is None or hasta is None:
            crud_liquidaciones.delete_by_informe_id(db, informe_id)
            inf.liquidacion_status = "COMPLETADO"
            resumen.liquidacion_status = "COMPLETADO"
            resumen.error = (
                "Sin proyectos resolubles o período inválido; nada que liquidar."
            )
            db.commit()
            logger.info("Liquidación informe %s: %s", informe_id, resumen.error)
            return resumen

        gen_rows = (
            db.query(
                GeneracionDiaria.proyecto_id,
                GeneracionDiaria.fecha,
                GeneracionDiaria.kwh_real,
            )
            .filter(
                GeneracionDiaria.proyecto_id.in_(proyecto_ids),
                GeneracionDiaria.fecha >= desde,
                GeneracionDiaria.fecha <= hasta,
                GeneracionDiaria.kwh_real.isnot(None),
            )
            .all()
        )

        # Precio de bolsa: si el MEM falla, no abortamos todo el proceso — se
        # generan filas con estado 'sin_precio' y se anota el error en el resumen.
        precios_por_fecha: dict[date, float] = {}
        try:
            precios = precios_fn(desde, hasta)
            precios_por_fecha = _precios_a_dict(precios)
        except Exception as exc:  # noqa: BLE001 — degradación controlada
            logger.error("Liquidación informe %s: MEM falló: %s", informe_id, exc)
            resumen.error = f"MEM no disponible: {exc}"

        generacion = [
            (pid, f, float(k) if isinstance(k, Decimal) else k)
            for (pid, f, k) in gen_rows
        ]
        filas = calcular_ingesta(informe_id, generacion, precios_por_fecha)

        # Escritura idempotente.
        crud_liquidaciones.delete_by_informe_id(db, informe_id)
        crud_liquidaciones.bulk_create_liquidacion_datos(db, filas)

        inf.liquidacion_status = "COMPLETADO"
        db.commit()

        resumen.liquidacion_status = "COMPLETADO"
        resumen.filas_creadas = len(filas)
        resumen.energia_total_kwh = round(
            sum(f.energia_generada_kwh for f in filas), 4
        )
        resumen.valor_liquidado_total_cop = round(
            sum(f.valor_liquidado_cop or 0.0 for f in filas), 4
        )
        resumen.dias_sin_precio = sum(
            1 for f in filas if f.estado_proceso == "sin_precio"
        )
        logger.info(
            "Liquidación informe %s OK: %s filas, %s kWh, %s COP (%s días sin precio)",
            informe_id, resumen.filas_creadas, resumen.energia_total_kwh,
            resumen.valor_liquidado_total_cop, resumen.dias_sin_precio,
        )
        return resumen

    except Exception as exc:  # noqa: BLE001
        logger.exception("Liquidación informe %s falló", informe_id)
        db.rollback()
        # Marca el informe en ERROR en una transacción aparte.
        try:
            inf2 = db.get(InformeGuardado, informe_id)
            if inf2 is not None:
                inf2.liquidacion_status = "ERROR"
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return LiquidacionIngestaResumen(
            informe_id=informe_id, liquidacion_status="ERROR", error=str(exc),
        )
