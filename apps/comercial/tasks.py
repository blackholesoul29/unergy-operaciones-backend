"""Tareas programadas del dominio `comercial`. Ver `apps/energia/tasks.py`."""

import logging

from celery import shared_task

logger = logging.getLogger("operaciones.tareas")


@shared_task(name="comercial.cerrar_contratos_vencidos")
def cerrar_contratos_vencidos() -> str:
    """Pasa a 'terminado' las ofertas cuyo contrato PPA ya pasó su `fecha_fin`.

    Justo después del cambio de día, para que el tablero amanezca correcto. Sin
    esto la etapa mentiría: nadie va a entrar al CRM el día que vence un
    contrato a moverlo a mano.
    """
    from apps.comercial.services.pipeline import cerrar_contratos_vencidos as cerrar

    cerradas = cerrar()
    logger.info("cierres por vencimiento: %d oferta(s) %s",
                len(cerradas), [c["codigo"] for c in cerradas] or "")
    return f"{len(cerradas)} oferta(s) a terminado"


@shared_task(name="comercial.backfill_oportunidades")
def backfill_oportunidades() -> str:
    """Crea la Oportunidad que le falta a un cliente con relación comercial real.

    El hueco lo dejan los clientes creados por el flujo directo (POST /clientes
    más el contrato a mano) en vez de por el pipeline de Comercial. Idempotente.
    No migra inversionistas puros, sin contrato ni PPA — esa decisión está en el
    docstring de `ejecutar_backfill`.

    Horario propio, aparte de los demás: estos no dependen de la API de
    generación de Unergy y no tienen por qué competir con los que sí.
    """
    from apps.comercial.services.mantenimiento import ejecutar_backfill

    res = ejecutar_backfill(usuario_id=None, dry_run=False,
                            solo_con_relacion_comercial=True)
    resumen = (f"{res['clientes_a_migrar']} clientes migrados, "
               f"{res['proyectos_a_vincular']} proyectos vinculados")
    logger.info("backfill comercial: %s", resumen)
    return resumen
