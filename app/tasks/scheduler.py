"""Scheduler de fondo para la propagación diaria Cliente → PPA.

Corre `ClientPpaSyncService.run_daily_sync()` cada día de madrugada. Vive en su
propio `BackgroundScheduler` (independiente del scheduler de MGS en main.py) para
que la lógica de sincronización de contratos sea fácil de razonar y desactivar.

Se ejecuta a las 02:30 — desfasado de la correlación cross-DB de las 02:00 para
no competir por la base de datos.
"""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger("tasks.scheduler")

SYNC_HOUR = 2
SYNC_MINUTE = 30

_scheduler = None


def _run_sync_safe() -> None:
    """Ejecuta el sync capturando cualquier excepción para no tumbar el scheduler."""
    try:
        from app.services.sync_client_ppa import run_daily_sync_job

        summary = run_daily_sync_job()
        logger.info("[client_ppa_sync] OK — %s", summary)
        print(
            f"[client_ppa_sync] OK — {summary.get('contratos_actualizados', 0)} contratos, "
            f"{summary.get('cambios_criticos', 0)} cambios críticos"
        )
    except Exception as e:  # noqa: BLE001 — el job nunca debe propagar
        logger.exception("[client_ppa_sync] FALLÓ")
        print(f"[client_ppa_sync] FAILED: {e}")
        _alert_failure(e)


def _alert_failure(exc: Exception) -> None:
    """Avisa a los administradores si el job de sincronización falla."""
    try:
        from app.core.database import SessionLocal
        from app.models import Usuario
        from app.models.notificaciones import Notificacion, TipoNotificacionEnum

        db = SessionLocal()
        try:
            usuarios = (
                db.query(Usuario)
                .filter(Usuario.activo == True, Usuario.rol == "admin")  # noqa: E712
                .all()
            )
            for u in usuarios:
                db.add(Notificacion(
                    usuario_id=u.id,
                    tipo=TipoNotificacionEnum.alerta,
                    titulo="Falló la sincronización Cliente → PPA",
                    mensaje=(
                        "El job diario de propagación de datos de clientes a contratos PPA "
                        f"falló: {exc}"
                    ),
                    link="/ppa",
                ))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        logger.exception("[client_ppa_sync] no se pudo notificar el fallo del job")


def start_scheduler():
    """Arranca el scheduler diario. Idempotente: no duplica el job si ya corre."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone=settings.TIMEZONE)
    _scheduler.add_job(
        _run_sync_safe,
        CronTrigger(hour=SYNC_HOUR, minute=SYNC_MINUTE, timezone=settings.TIMEZONE),
        id="client_ppa_sync",
        name="Daily Cliente → PPA data sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "[tasks.scheduler] started — client_ppa_sync @ %02d:%02d %s",
        SYNC_HOUR, SYNC_MINUTE, settings.TIMEZONE,
    )
    print(f"[startup] client_ppa_sync scheduler started (@ {SYNC_HOUR:02d}:{SYNC_MINUTE:02d})")
    return _scheduler


def shutdown_scheduler(wait: bool = False) -> None:
    """Detiene el scheduler de forma ordenada (llamado en el shutdown de la app)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
        print("[shutdown] client_ppa_sync scheduler stopped")
