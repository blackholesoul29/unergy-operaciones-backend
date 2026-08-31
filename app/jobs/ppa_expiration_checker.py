"""Job diario: alertas proactivas de vencimiento de contratos PPA.

Para cada contrato PPA activo con `fecha_fin` dentro del horizonte (el mayor
umbral configurado en `settings.PPA_ALERT_DAYS`, ej. 90/60/30 dias) dispara la
ventana de alerta MAS AJUSTADA que el contrato ya cruzo (`dias <= umbral`) y, si
aun no existe una alerta para esa ventana, la crea y notifica por correo.

Se usa cruce por umbral (`<=`) en vez de coincidencia exacta (`==`) a proposito:
asi el job es tolerante a corridas perdidas (deploy, downtime) y a contratos
dados de alta ya dentro de una ventana (backfill de PPAs existentes). Con `==`
un contrato importado a 45 dias nunca dispararia 90/60 y uno importado a <30
dias no dispararia NUNCA -- el equipo quedaria a ciegas. Con `<=` siempre se
emite la alerta pendiente mas urgente.

Idempotente: la restriccion unica (ppa_id, days_to_expiration) mas el chequeo
`get_alerta_by_ppa_and_days` garantizan que correr el job dos veces no duplica
la alerta de la misma ventana. Un contrato escala de ventana en ventana (60 -> 30)
creando una alerta distinta por cada umbral que va cruzando.

Canal de notificacion: correo via app.services.email_service, mismo patron que
_scheduled_representacion_alertas (app/main.py) ya usa para las alertas de
vencimiento de Representacion/CGM -- no Slack, no hay webhook configurado en
el proyecto y el correo ya funciona sin infraestructura nueva.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.crud import crud_alertas
from app.models.contratos import PPAContrato
from app.schemas.alerta import AlertaCreate
from app.services.email_service import _smtp_send, _log_send

logger = logging.getLogger("jobs.ppa_expiration_checker")

ALERT_TYPE_PPA_EXPIRING = "PPA_EXPIRING"


def _parse_alert_emails(raw: str) -> list[str]:
    """'a@x.com, b@x.com' -> ['a@x.com', 'b@x.com']; ignora tokens vacios."""
    return [tok.strip() for tok in (raw or "").split(",") if tok.strip()]


def _parse_alert_days(raw: str) -> list[int]:
    """'90,60,30' -> [90, 60, 30]; ignora tokens vacios o no numericos."""
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
    """Umbral de alerta mas ajustado (el menor) que el contrato YA cruzo.

    `dias` = dias desde hoy hasta `fecha_fin`. Devuelve el menor umbral `T` de
    `umbrales` tal que `0 <= dias <= T`, o `None` si el contrato aun no entra en
    ninguna ventana (`dias` mayor que todos los umbrales) o ya vencio (`dias < 0`).

    Elegir el umbral MAS AJUSTADO evita avisar "faltan 90 dias" a un contrato que
    en realidad esta a 45: se emite la ventana mas urgente pendiente y, al cruzar
    la siguiente, se emite otra (escalada 90 -> 60 -> 30).
    """
    if dias < 0:
        return None
    cruzados = [t for t in umbrales if dias <= t]
    return min(cruzados) if cruzados else None


def _build_message(ppa: PPAContrato, project_name: Optional[str], dias: int) -> str:
    partes = [f"Contrato PPA por vencer -- {_ppa_label(ppa)}"]
    if ppa.comprador_nombre:
        partes.append(f"Comprador: {ppa.comprador_nombre}")
    if project_name:
        partes.append(f"Proyecto: {project_name}")
    vence = ppa.fecha_fin.strftime("%d/%m/%Y") if ppa.fecha_fin else "-"
    cuando = "hoy" if dias == 0 else f"en {dias} dia{'s' if dias != 1 else ''}"
    partes.append(f"Vence el {vence} ({cuando}).")
    return "\n".join(partes)


def _enviar_correo(mensaje: str, dias: int) -> bool:
    """Envia la alerta por correo. Best-effort: una falla de envio NO debe
    tumbar el job -- la alerta ya quedo persistida antes de llegar aca."""
    destinatarios = _parse_alert_emails(settings.PPA_ALERT_EMAILS)
    if not settings.SMTP_HOST or not destinatarios:
        return False
    subject = f"Contrato PPA por vencer en {dias} dia{'s' if dias != 1 else ''}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(mensaje, "plain", "utf-8"))
    try:
        _smtp_send(msg, destinatarios)
        _log_send(
            to_email=destinatarios[0], cc=destinatarios[1:],
            subject=subject, tipo="alerta_ppa_vencimiento", success=True,
        )
        return True
    except Exception as exc:
        _log_send(
            to_email=destinatarios[0], cc=destinatarios[1:],
            subject=subject, tipo="alerta_ppa_vencimiento", success=False,
            error_msg=str(exc),
        )
        return False


def check_ppa_expirations(db: Optional[Session] = None) -> list[int]:
    """Revisa vencimientos de PPA y crea/notifica alertas.

    Devuelve la lista de ids de las alertas creadas en esta corrida (vacia si no
    hubo ninguna nueva). `db` es inyectable para pruebas.
    """
    owns_session = db is None
    db = db or SessionLocal()

    created_ids: list[int] = []
    try:
        umbrales = _parse_alert_days(settings.PPA_ALERT_DAYS)
        if not umbrales:
            return created_ids

        hoy = date.today()
        horizonte = hoy + timedelta(days=max(umbrales))
        # Un solo barrido de los contratos dentro del horizonte; para cada uno se
        # elige la ventana mas ajustada ya cruzada (tolerante a corridas perdidas
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
            if project_id is None:
                logger.warning(
                    "PPA %s (%s) sin ningun proyecto vinculado -- la alerta de "
                    "vencimiento se crea con project_id=NULL",
                    ppa.id, _ppa_label(ppa),
                )

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
            _enviar_correo(mensaje, umbral)
    finally:
        if owns_session:
            db.close()

    return created_ids
