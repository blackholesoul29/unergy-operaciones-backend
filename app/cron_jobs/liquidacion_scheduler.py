"""Ejecución automática del motor de liquidación (cron mensual).

El día 1 de cada mes liquida el MES ANTERIOR para todos los proyectos en
operación: itera los proyectos y dispara `LiquidacionEngine` para cada uno,
registrando el resultado y los errores de datos faltantes sin abortar el lote.

Uso:
  * Integrado en un proceso con APScheduler:
        from app.cron_jobs.liquidacion_scheduler import registrar_jobs
        registrar_jobs(scheduler)   # scheduler: BackgroundScheduler ya creado
  * Standalone (proceso dedicado):
        python -m app.cron_jobs.liquidacion_scheduler
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.proyectos import Proyecto, EstadoProyectoEnum
from app.services.liquidacion_engine import (
    LiquidacionEngine, DatosFaltantesError, LiquidacionEngineError,
)

logger = logging.getLogger(__name__)


@dataclass
class ResumenBatch:
    """Resultado agregado de una corrida en lote (para logs y tests)."""
    anio: int
    mes: int
    total_proyectos: int = 0
    calculados: int = 0
    sin_datos: int = 0
    errores: int = 0
    detalle_errores: list[str] = field(default_factory=list)


def periodo_anterior(hoy: date) -> tuple[int, int]:
    """Devuelve (año, mes) del mes anterior a `hoy`. Función pura (testeable)."""
    if hoy.month == 1:
        return hoy.year - 1, 12
    return hoy.year, hoy.month - 1


def ejecutar_liquidacion_mensual_batch(db: Session, anio: int, mes: int) -> ResumenBatch:
    """Liquida (año, mes) para todos los proyectos en operación.

    No aborta el lote ante un proyecto sin datos o con error: lo cuenta y sigue.
    Cada proyecto se calcula en su propia transacción (el engine hace commit),
    así que un fallo aislado no descarta lo ya calculado.
    """
    resumen = ResumenBatch(anio=anio, mes=mes)
    engine = LiquidacionEngine(db)

    proyectos = (
        db.query(Proyecto.id, Proyecto.nombre_comercial)
        .filter(Proyecto.estado == EstadoProyectoEnum.en_operacion)
        .all()
    )
    resumen.total_proyectos = len(proyectos)
    logger.info(
        "[liquidacion-cron] Iniciando lote %s-%02d para %d proyectos en operación",
        anio, mes, resumen.total_proyectos,
    )

    for pid, nombre in proyectos:
        try:
            engine.calcular_liquidacion_proyecto(pid, mes, anio)
            resumen.calculados += 1
        except DatosFaltantesError as exc:
            resumen.sin_datos += 1
            logger.info("[liquidacion-cron] Proyecto %s (%s) sin datos: %s", pid, nombre, exc)
            db.rollback()
        except LiquidacionEngineError as exc:
            resumen.errores += 1
            resumen.detalle_errores.append(f"{pid}: {exc}")
            logger.warning("[liquidacion-cron] Proyecto %s (%s) error: %s", pid, nombre, exc)
            db.rollback()
        except Exception as exc:  # noqa: BLE001 — un proyecto no puede tumbar el lote
            resumen.errores += 1
            resumen.detalle_errores.append(f"{pid}: {exc}")
            logger.exception("[liquidacion-cron] Proyecto %s (%s) error inesperado", pid, nombre)
            db.rollback()

    logger.info(
        "[liquidacion-cron] Lote %s-%02d terminado: %d calculados, %d sin datos, %d errores",
        anio, mes, resumen.calculados, resumen.sin_datos, resumen.errores,
    )
    return resumen


def run_liquidacion_mes_anterior() -> ResumenBatch:
    """Punto de entrada del job cron: liquida el mes anterior a hoy."""
    anio, mes = periodo_anterior(date.today())
    db = SessionLocal()
    try:
        return ejecutar_liquidacion_mensual_batch(db, anio, mes)
    finally:
        db.close()


def registrar_jobs(scheduler) -> None:
    """Registra el job mensual en un APScheduler ya existente.

    Corre el día 1 de cada mes a las 03:00 (hora del proceso), liquidando el mes
    anterior. `id` fijo + `replace_existing` para que re-registrar sea idempotente.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        run_liquidacion_mes_anterior,
        CronTrigger(day=1, hour=3, minute=0),
        id="liquidacion_mensual",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("[liquidacion-cron] Job 'liquidacion_mensual' registrado (día 1, 03:00)")


def main() -> None:
    """Ejecución standalone: levanta un scheduler bloqueante con solo este job."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    logging.basicConfig(level=logging.INFO)
    scheduler = BlockingScheduler(timezone="America/Bogota")
    registrar_jobs(scheduler)
    logger.info("[liquidacion-cron] Scheduler standalone iniciado (Ctrl+C para salir)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[liquidacion-cron] Scheduler detenido")


if __name__ == "__main__":
    main()
