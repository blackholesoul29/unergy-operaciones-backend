"""Job diario: alertas proactivas de vencimiento de contratos PPA.

Para cada contrato PPA activo con `fecha_fin` dentro del horizonte (el mayor
umbral configurado en `settings.PPA_ALERT_DAYS`, ej. 90/60/30 días) dispara la
ventana de alerta MÁS AJUSTADA que el contrato ya cruzó (`dias <= umbral`) y, si
aún no existe una alerta para esa ventana, la crea y notifica a Slack.

Se usa cruce por umbral (`<=`) en vez de coincidencia exacta (`==`) a propósito:
así el job es tolerante a corridas perdidas (deploy, downtime) y a contratos
dados de alta ya dentro de una ventana (backfill de PPAs existentes). Con `==`
un contrato importado a 45 días nunca dispararía 90/60 y uno importado a <30
días no dispararía NUNCA — el equipo quedaría a ciegas. Con `<=` siempre se
emite la alerta pendiente más urgente.

Idempotente: la restricción única (ppa_id, days_to_expiration) más el chequeo
`get_alerta_by_ppa_and_days` garantizan que correr el job dos veces no duplica
la alerta de la misma ventana. Un contrato escala de ventana en ventana (60 → 30)
creando una alerta distinta por cada umbral que va cruzando.
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


def _pick_threshold(dias: int, umbrales: list[int]) -> Optional[int]:
    """Umbral de alerta más ajustado (el menor) que el contrato YA cruzó.

    `dias` = días desde hoy hasta `fecha_fin`. Devuelve el menor umbral `T` de
    `umbrales` tal que `0 <= dias <= T`, o `None` si el contrato aún no entra en
    ninguna ventana (`dias` mayor que todos los umbrales) o ya venció (`dias < 0`).

    Elegir el umbral MÁS AJUSTADO evita avisar "faltan 90 días" a un contrato que
    en realidad está a 45: se emite la ventana más urgente pendiente y, al cruzar
    la siguiente, se emite otra (escalada 90 → 60 → 30).
    """
    if dias < 0:
        return None
    cruzados = [t for t in umbrales if dias <= t]
    return min(cruzados) if cruzados else None


def _build_message(ppa: PPAContrato, project_name: Optional[str], dias: int) -> str:
    partes = [f"⚠️ *Contrato PPA por vencer* — {_ppa_label(ppa)}"]
    if ppa.comprador_nombre:
        partes.append(f"Comprador: {ppa.comprador_nombre}")
    if project_name:
        partes.append(f"Proyecto: {project_name}")
    vence = ppa.fecha_fin.strftime("%d/%m/%Y") if ppa.fecha_fin else "—"
    cuando = "hoy" if dias == 0 else f"en {dias} día{'s' if dias != 1 else ''}"
    partes.append(f"Vence el {vence} ({cuando}).")
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
        umbrales = _parse_alert_days(settings.PPA_ALERT_DAYS)
        if not umbrales:
            return created_ids

        hoy = date.today()
        horizonte = hoy + timedelta(days=max(umbrales))
        # Un solo barrido de los contratos dentro del horizonte; para cada uno se
        # elige la ventana más ajustada ya cruzada (tolerante a corridas perdidas
        # y a contratos importados ya dentro de una ventana).
        contratos = (
            db.query(PPAContrato)
            .filter(
                PPAContrato.fecha_fin.isnot(None),
                PPAContrato.fecha_fin >= hoy,
                PPAContrato.fecha_fin <= horizonte,
                PPAContrato.deleted_at.is_(None),
            )
            .all()
        )
        for ppa in contratos:
            dias = (ppa.fecha_fin - hoy).days
            umbral = _pick_threshold(dias, umbrales)
            if umbral is None:
                continue
            if crud_alertas.get_alerta_by_ppa_and_days(db, ppa.id, umbral):
                continue  # ya alertado para esta ventana

            # Un PPA se vincula a 0..N proyectos (m2m); toma el primero si existe.
            proyectos = ppa.proyectos or []
            project_id = proyectos[0].id if proyectos else None
            project_name = proyectos[0].nombre_comercial if proyectos else None

            mensaje = _build_message(ppa, project_name, dias)
            alerta = crud_alertas.create_alerta(
                db,
                AlertaCreate(
                    ppa_id=ppa.id,
                    project_id=project_id,
                    alert_type=ALERT_TYPE_PPA_EXPIRING,
                    description=mensaje,
                    due_date=ppa.fecha_fin,
                    days_to_expiration=umbral,
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
