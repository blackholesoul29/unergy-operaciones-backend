"""Entrypoint de background para la automatización de liquidación XM.

Lo dispara la aprobación de un informe (``BackgroundTasks`` en
``app/api/v1/informes.py``) y también sirve como target para APScheduler si se
quisiera programar una reprocesada. Abre su PROPIA sesión de DB porque corre
fuera del ciclo de request (la sesión del request ya se cerró).
"""
from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.services.liquidaciones_orchestrator import run_liquidacion_proceso

logger = logging.getLogger(__name__)


def trigger_liquidacion_proceso(informe_id: int) -> None:
    """Corre la liquidación de un informe con una sesión propia.

    Nunca propaga excepciones: es un job de fondo; los errores se registran y el
    orquestador ya deja el informe en estado ``ERROR`` de forma transaccional.
    """
    logger.info("Job liquidación disparado para informe %s", informe_id)
    db = SessionLocal()
    try:
        resumen = run_liquidacion_proceso(db, informe_id)
        logger.info(
            "Job liquidación informe %s terminó: status=%s filas=%s",
            informe_id, resumen.liquidacion_status, resumen.filas_creadas,
        )
    except Exception:  # noqa: BLE001 — job de fondo, no debe tumbar el worker
        logger.exception("Job liquidación informe %s crashó", informe_id)
    finally:
        db.close()
