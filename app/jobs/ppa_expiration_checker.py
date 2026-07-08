"""Job diario: alertas proactivas de vencimiento de contratos PPA.

Para cada ventana de antelación configurada en `settings.PPA_ALERT_DAYS`
(ej. 90/60/30 días), busca los contratos PPA activos cuyo `fecha_fin` cae
exactamente ese día y, si aún no existe una alerta para esa ventana, la crea
y notifica a Slack.

Idempotente: la restricción única (ppa_id, days_to_expiration) más el chequeo
`get_alerta_by_ppa_and_days` garantizan que correr el job dos veces no duplica
la alerta de la misma ventana.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.crud import crud_alertas
from app.models.contratos import PPAContrato
from app.schemas.alerta import AlertaCreate
from app.services.notification_service import NotificationService

ALERT_TYPE_PPA_EXPIRING = "PPA_EXPIRING"


def _parse_alert_days(raw: str) -> list[int]:
    """'90,60,30' -> [90, 60, 30]; ignora tokens vacíos o no numéricos."""
    dias: list[int] = []
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            dias.append(int(tok))
        except ValueError:
            continue
    return dias


def _ppa_label(ppa: PPAContrato) -> str:
    """Nombre legible del contrato para el mensaje."""
    return ppa.nombre_interno or ppa.numero_codigo_contrato or f"PPA #{ppa.id}"


def _build_message(ppa: PPAContrato, project_name: Optional[str], days: int) -> str:
    partes = [f"⚠️ *Contrato PPA por vencer* — {_ppa_label(ppa)}"]
    if ppa.comprador_nombre:
        partes.append(f"Comprador: {ppa.comprador_nombre}")
    if project_name:
        partes.append(f"Proyecto: {project_name}")
    partes.append(f"Vence el {ppa.fecha_fin} (en {days} días).")
    return "\n".join(partes)


async def check_ppa_expirations(
    db: Optional[Session] = None,
    notifier: Optional[NotificationService] = None,
) -> list[int]:
    """Revisa vencimientos de PPA y crea/notifica alertas.

    Devuelve la lista de ids de las alertas creadas en esta corrida (vacía si no
    hubo ninguna nueva). `db` y `notifier` son inyectables para pruebas.
    """
    owns_session = db is None
    db = db or SessionLocal()
    notifier = notifier or NotificationService()
    webhook = settings.SLACK_WEBHOOK_URL_OPERATIONS or ""

    created_ids: list[int] = []
    try:
        hoy = date.today()
        for days in _parse_alert_days(settings.PPA_ALERT_DAYS):
            objetivo = hoy + timedelta(days=days)
            contratos = (
                db.query(PPAContrato)
                .filter(
                    PPAContrato.fecha_fin == objetivo,
                    PPAContrato.deleted_at.is_(None),
                )
                .all()
            )
            for ppa in contratos:
                if crud_alertas.get_alerta_by_ppa_and_days(db, ppa.id, days):
                    continue  # ya alertado para esta ventana

                # Un PPA se vincula a 0..N proyectos (m2m); toma el primero si existe.
                proyectos = ppa.proyectos or []
                project_id = proyectos[0].id if proyectos else None
                project_name = proyectos[0].nombre_comercial if proyectos else None

                mensaje = _build_message(ppa, project_name, days)
                alerta = crud_alertas.create_alerta(
                    db,
                    AlertaCreate(
                        ppa_id=ppa.id,
                        project_id=project_id,
                        alert_type=ALERT_TYPE_PPA_EXPIRING,
                        description=mensaje,
                        due_date=ppa.fecha_fin,
                        days_to_expiration=days,
                        status="new",
                    ),
                )
                created_ids.append(alerta.id)

                if webhook:
                    await notifier.send_slack_notification(webhook, mensaje)
    finally:
        if owns_session:
            db.close()

    return created_ids
