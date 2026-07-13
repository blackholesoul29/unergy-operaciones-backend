"""
Motor de cierre mensual de cumplimiento PPA.

Envuelve la lógica que ya vive en `POST /cumplimiento/cerrar-periodo` para que
pueda ejecutarse fuera de una request HTTP (scheduler, scripts) y deja traza de
cada corrida en `cumplimiento_cierre_log`.

El cálculo NO se duplica aquí: el endpoint sigue siendo la única fuente de la
lógica (generación real desde Unergy + compromisos PPA + precio de bolsa, con
upsert sobre `cumplimiento_mensual`). Este módulo solo aporta orquestación,
selección de periodo y bitácora.
"""
import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def periodo_anterior(hoy: date) -> tuple[int, int]:
    """(anio, mes) del mes calendario anterior a `hoy`."""
    if hoy.month == 1:
        return hoy.year - 1, 12
    return hoy.year, hoy.month - 1


def registrar_cierre(
    db: Session,
    anio: int,
    mes: int,
    *,
    origen: str,
    contratos_procesados: int = 0,
    contratos_con_deficit: int = 0,
    contratos_cumplidos: int = 0,
    error: str | None = None,
) -> None:
    """Deja constancia de la corrida en cumplimiento_cierre_log (best-effort)."""
    try:
        db.execute(text("""
            INSERT INTO cumplimiento_cierre_log
                (anio, mes, origen, contratos_procesados, contratos_con_deficit,
                 contratos_cumplidos, error)
            VALUES (:anio, :mes, :origen, :procesados, :deficit, :cumplidos, :error)
        """), {
            "anio": anio,
            "mes": mes,
            "origen": origen,
            "procesados": contratos_procesados,
            "deficit": contratos_con_deficit,
            "cumplidos": contratos_cumplidos,
            "error": error,
        })
        db.commit()
    except Exception as exc:  # la bitácora nunca debe tumbar el cierre
        db.rollback()
        logger.warning("No se pudo registrar cumplimiento_cierre_log: %s", exc)


def cerrar_periodo_mes(db: Session, anio: int, mes: int, *, origen: str = "scheduler") -> dict:
    """
    Ejecuta el cierre de cumplimiento del periodo (anio, mes) y lo registra.

    Reutiliza `cerrar_periodo` del router. Es idempotente: el endpoint hace
    upsert por (contrato, anio, mes) y respeta los registros ya `facturado`.

    Re-lanza la excepción tras registrar el error, para que el llamador decida.
    """
    # Import diferido: el router importa este módulo para exponer /cierre-status.
    from app.api.v1.cumplimiento import cerrar_periodo
    from app.schemas.cumplimiento import CerrarPeriodoRequest

    try:
        resultado = cerrar_periodo(CerrarPeriodoRequest(anio=anio, mes=mes), db=db, _=None)
    except Exception as exc:
        db.rollback()
        registrar_cierre(db, anio, mes, origen=origen, error=str(exc)[:500])
        raise

    registrar_cierre(
        db, anio, mes,
        origen=origen,
        contratos_procesados=resultado.get("contratos_procesados", 0),
        contratos_con_deficit=resultado.get("contratos_con_deficit", 0),
        contratos_cumplidos=resultado.get("contratos_cumplidos", 0),
    )
    return resultado


def ultimo_cierre(db: Session) -> dict | None:
    """Última corrida registrada, para el health check del scheduler."""
    row = db.execute(text("""
        SELECT anio, mes, origen, contratos_procesados, contratos_con_deficit,
               contratos_cumplidos, error, ejecutado_at
        FROM cumplimiento_cierre_log
        ORDER BY ejecutado_at DESC
        LIMIT 1
    """)).first()
    if not row:
        return None
    return {
        "anio": row.anio,
        "mes": row.mes,
        "origen": row.origen,
        "contratos_procesados": row.contratos_procesados,
        "contratos_con_deficit": row.contratos_con_deficit,
        "contratos_cumplidos": row.contratos_cumplidos,
        "error": row.error,
        "ok": row.error is None,
        "ejecutado_at": row.ejecutado_at.isoformat() if row.ejecutado_at else None,
    }
