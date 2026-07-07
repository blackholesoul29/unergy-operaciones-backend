"""Notificaciones de alertas de auditoría — Slack + correo.

`NotificationService` envía una `AuditAlert` por Slack (incoming webhook vía
`httpx`) y por correo (reutilizando el envío SMTP de `email_service`). Ambos
canales son best-effort: si el canal no está configurado, se registra en logs y
se continúa; nunca se propaga una excepción que rompa el scan de auditoría.
"""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Optional

import httpx

from app.core.config import settings

if TYPE_CHECKING:  # evita import circular en runtime
    from app.models.audit_alert import AuditAlert

logger = logging.getLogger("audit.notifications")

_SEVERITY_COLOR = {"critical": "#FF3B30", "medium": "#FF9500", "low": "#34C759"}
_SEVERITY_LABEL = {"critical": "CRÍTICA", "medium": "MEDIA", "low": "BAJA"}


class NotificationService:
    """Despacha alertas de auditoría a Slack y correo."""

    def __init__(
        self,
        *,
        slack_webhook_url: Optional[str] = None,
        email_recipients: Optional[list[str]] = None,
    ) -> None:
        self.slack_webhook_url = (
            slack_webhook_url if slack_webhook_url is not None else settings.SLACK_WEBHOOK_URL
        )
        if email_recipients is None:
            email_recipients = [
                e.strip() for e in (settings.ALERT_EMAIL_RECIPIENTS or "").split(",") if e.strip()
            ]
        self.email_recipients = email_recipients

    # ── helpers de presentación ──────────────────────────────────────────────
    def _record_link(self, alert: "AuditAlert") -> str:
        """Link directo al registro afectado en el frontend."""
        base = (settings.FRONTEND_URL or "").rstrip("/")
        # Mapa entidad → ruta del frontend.
        path = {
            "liquidacion": "liquidaciones",
            "ppa": "ppa",
            "generacion": "generacion",
        }.get(alert.entity_type, alert.entity_type)
        return f"{base}/{path}/{alert.entity_id}" if base else ""

    # ── Slack ────────────────────────────────────────────────────────────────
    def send_slack_alert(self, alert: "AuditAlert") -> bool:
        if not self.slack_webhook_url:
            logger.info("[audit_slack] webhook no configurado — alerta %s no enviada", alert.id)
            return False

        color = _SEVERITY_COLOR.get(alert.severity, "#8E8E93")
        label = _SEVERITY_LABEL.get(alert.severity, alert.severity)
        link = self._record_link(alert)
        fields = [
            {"title": "Entidad", "value": f"{alert.entity_type} #{alert.entity_id}", "short": True},
            {"title": "Usuario", "value": alert.usuario_nombre or "—", "short": True},
            {"title": "Regla", "value": alert.rule_name, "short": True},
            {"title": "Severidad", "value": label, "short": True},
        ]
        payload = {
            "attachments": [{
                "color": color,
                "title": f"[{label}] Alerta de auditoría — {alert.entity_type}",
                "title_link": link or None,
                "text": alert.trigger_reason,
                "fields": fields,
                "footer": "Monitoreo de auditoría Unergy",
                "ts": int(alert.created_at.timestamp()) if alert.created_at else None,
            }]
        }
        try:
            resp = httpx.post(self.slack_webhook_url, json=payload, timeout=10.0)
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("[audit_slack] fallo enviando alerta %s: %s", alert.id, exc)
            return False

    # ── Correo ───────────────────────────────────────────────────────────────
    def send_email_alert(self, alert: "AuditAlert") -> bool:
        if not self.email_recipients:
            logger.info("[audit_email] sin destinatarios — alerta %s no enviada", alert.id)
            return False
        if not settings.SMTP_HOST:
            logger.info("[audit_email] SMTP no configurado — alerta %s no enviada", alert.id)
            return False

        label = _SEVERITY_LABEL.get(alert.severity, alert.severity)
        color = _SEVERITY_COLOR.get(alert.severity, "#8E8E93")
        link = self._record_link(alert)
        ts = alert.created_at.isoformat() if alert.created_at else "—"
        cta = (
            f'<a href="{link}" style="color:#915BD8">Ver registro afectado →</a>'
            if link else "Registro afectado en la plataforma."
        )
        subject = f"[{label}] Auditoría — {alert.entity_type} #{alert.entity_id}"
        body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:560px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Alerta de auditoría</div>
  </div>
  <div style="background:#F7F4FD;padding:24px 28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <div style="background:{color};color:#fff;display:inline-block;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:700;margin-bottom:16px">{label}</div>
    <h2 style="margin:0 0 8px;font-size:18px">{alert.entity_type} #{alert.entity_id}</h2>
    <p style="margin:0 0 6px;color:#6B5F80"><strong>Regla:</strong> {alert.rule_name}</p>
    <p style="margin:0 0 6px;color:#6B5F80"><strong>Usuario:</strong> {alert.usuario_nombre or "—"}</p>
    <p style="margin:0 0 16px;color:#6B5F80"><strong>Fecha:</strong> {ts}</p>
    <div style="background:#fff;border:1px solid #EDE8F5;border-radius:8px;padding:14px 18px;margin:0 0 20px">
      <div style="font-size:11px;font-weight:700;color:#A89EC0;letter-spacing:.7px;text-transform:uppercase;margin-bottom:6px">MOTIVO</div>
      <div style="font-size:14px;color:#1A0F2E">{alert.trigger_reason}</div>
    </div>
    <p style="font-size:13px;margin:0">{cta}</p>
  </div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = ", ".join(self.email_recipients)
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        try:
            from app.services.email_service import _smtp_send
            _smtp_send(msg, self.email_recipients)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("[audit_email] fallo enviando alerta %s: %s", alert.id, exc)
            return False

    # ── despacho combinado ───────────────────────────────────────────────────
    def dispatch(self, alert: "AuditAlert") -> dict:
        """Envía por todos los canales. Devuelve el resultado por canal."""
        slack_ok = self.send_slack_alert(alert)
        email_ok = self.send_email_alert(alert)
        return {"slack": slack_ok, "email": email_ok}
