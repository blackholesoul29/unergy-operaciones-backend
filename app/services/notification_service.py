"""Servicio de notificaciones — desacopla el envío (Slack / email) de la lógica
de negocio que decide QUÉ notificar.

Slack se envía por webhook entrante (Incoming Webhook) con `httpx.AsyncClient`.
El formato del mensaje debe dejar claro qué contrato PPA / proyecto vence y cuándo.
"""
from __future__ import annotations

import httpx


class NotificationService:
    """Envía notificaciones a los canales configurados (Slack, email)."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def send_slack_notification(self, webhook_url: str, message: str) -> bool:
        """Publica `message` en el webhook de Slack. Devuelve True si tuvo éxito.

        No lanza excepción hacia el llamante: una notificación fallida NO debe
        tumbar el job que ya persistió la alerta. Un webhook vacío se ignora.
        """
        if not webhook_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(webhook_url, json={"text": message})
                resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001 — best-effort, no debe propagar
            print(f"[notification_service] Slack falló: {e}")
            return False

    def send_email_notification(
        self, to: str, subject: str, body: str
    ) -> bool:  # pragma: no cover - placeholder
        """Placeholder para notificación por email.

        El envío real de correo del proyecto vive en `app/services/email_service.py`
        (`_smtp_send`); aquí queda el enganche para futuras alertas por email.
        """
        raise NotImplementedError("send_email_notification aún no implementado")
