"""
Servicio de email para envio de informes aprobados.
Usa Playwright (Chromium headless) para generar el PDF y smtplib para enviarlo.
"""
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from app.core.config import settings

logger = logging.getLogger("email_service")


def _log_send(
    *,
    to_email: str,
    cc: list[str] | None,
    subject: str,
    tipo: str,
    success: bool,
    error_msg: str | None = None,
) -> None:
    """Log email send to database (fire-and-forget)."""
    try:
        from app.core.database import SessionLocal
        from sqlalchemy import text as sa_text
        db = SessionLocal()
        try:
            db.execute(sa_text("""
                INSERT INTO email_envios
                    (destinatario, cc, asunto, tipo, exitoso, error, enviado_at)
                VALUES (:to, :cc, :subject, :tipo, :ok, :err, :ts)
            """), {
                "to": to_email,
                "cc": ",".join(cc) if cc else None,
                "subject": subject,
                "tipo": tipo,
                "ok": success,
                "err": error_msg,
                "ts": datetime.now(timezone.utc),
            })
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("Failed to log email send: %s", e)
        finally:
            db.close()
    except Exception:
        pass


def _build_pdf(html: str) -> bytes:
    """Genera PDF desde HTML usando Playwright (Chromium headless)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright no está instalado. Instálalo con: pip install playwright && playwright install chromium"
        )
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        pdf_bytes = page.pdf(
            format="A4",
            margin={"top": "12mm", "bottom": "12mm", "left": "14mm", "right": "14mm"},
            print_background=True,
        )
        browser.close()
        return pdf_bytes


def send_otp_email(*, to_email: str, codigo: str) -> None:
    """
    Envía el código OTP de 6 dígitos al correo indicado.
    Si SMTP no está configurado, imprime el código en los logs del servidor
    (útil para desarrollo/staging).
    """
    if not settings.SMTP_HOST:
        print(f"[OTP] Código para {to_email}: {codigo}  (SMTP no configurado — solo en logs)")
        return

    subject = "Tu código de acceso — Monitoreo Unergy"
    body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:480px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Código de acceso</div>
  </div>
  <div style="background:#F7F4FD;padding:28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <p style="margin:0 0 20px">Usa el siguiente código para ingresar al módulo de monitoreo:</p>
    <div style="background:#fff;border:2px solid #915BD8;border-radius:10px;padding:20px;text-align:center;margin:0 0 20px">
      <div style="font-size:38px;font-weight:900;letter-spacing:10px;color:#1A0F2E;font-family:monospace">{codigo}</div>
      <div style="font-size:12px;color:#A89EC0;margin-top:8px">Válido por 10 minutos</div>
    </div>
    <p style="color:#6B5F80;font-size:12px;margin:0">
      Si no solicitaste este código, ignora este correo.<br>
      Contacto: <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        _log_send(to_email=to_email, cc=None, subject=subject, tipo="otp", success=True)
    except Exception as exc:
        _log_send(to_email=to_email, cc=None, subject=subject, tipo="otp", success=False, error_msg=str(exc))
        print(f"[OTP] Error enviando email a {to_email}: {exc} — código: {codigo}")
        raise RuntimeError(f"No se pudo enviar el código: {exc}") from exc


def send_reset_password_email(*, to_email: str, token: str) -> None:
    """
    Envía el enlace de restablecimiento de contraseña al correo indicado.
    Si SMTP no está configurado, imprime el token en los logs del servidor.
    """
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    if not settings.SMTP_HOST:
        print(f"[RESET] Token para {to_email}: {token}  (SMTP no configurado — solo en logs)")
        print(f"[RESET] URL: {reset_url}")
        return

    subject = "Restablecer contraseña — Monitoreo Unergy"
    body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:480px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Restablecer contraseña</div>
  </div>
  <div style="background:#F7F4FD;padding:28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <p style="margin:0 0 20px">Recibimos una solicitud para restablecer tu contraseña. Haz clic en el siguiente enlace:</p>
    <div style="text-align:center;margin:0 0 20px">
      <a href="{reset_url}" style="background:#915BD8;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:700;display:inline-block">Restablecer contraseña</a>
    </div>
    <p style="color:#6B5F80;font-size:12px;margin:0">
      Este enlace es válido por 1 hora.<br>
      Si no solicitaste este cambio, ignora este correo.<br>
      Contacto: <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
    except Exception as exc:
        print(f"[RESET] Error enviando email a {to_email}: {exc}")
        raise RuntimeError(f"No se pudo enviar el email: {exc}") from exc


def send_informe_email(
    *,
    to_email: str,
    cc: list[str] | None = None,
    proyecto_nombre: str,
    periodo_display: str,
    aprobado_por: str,
    html_content: str,
) -> None:
    """
    Genera el PDF del informe con Playwright y lo envía como adjunto por correo.
    Lanza RuntimeError si SMTP no está configurado o falla el envío.
    """
    if not settings.SMTP_HOST:
        raise RuntimeError(
            "SMTP no configurado. Define SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD y SMTP_FROM en las variables de entorno."
        )

    # HTML completo para el PDF (incluir estilos base)
    html_for_pdf = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4 portrait; margin: 12mm 14mm; }}
  * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }}
  body {{ margin: 0; padding: 0; background: #fff; font-family: Arial, sans-serif; }}
</style>
</head>
<body>{html_content}</body>
</html>"""

    pdf_bytes = _build_pdf(html_for_pdf)

    subject = f"Informe Operacional — {proyecto_nombre} — {periodo_display}"

    body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:620px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Informe Operacional</div>
  </div>
  <div style="background:#F7F4FD;padding:24px 28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <p style="margin:0 0 16px">Estimado cliente,</p>
    <p style="margin:0 0 16px">
      Adjunto encontrará el <strong>Informe Operacional de {proyecto_nombre}</strong>
      correspondiente al período <strong>{periodo_display}</strong>.
    </p>
    <div style="background:#fff;border:1px solid #EDE8F5;border-radius:8px;padding:14px 18px;margin:20px 0">
      <div style="font-size:11px;font-weight:700;color:#A89EC0;letter-spacing:.7px;text-transform:uppercase;margin-bottom:6px">APROBADO POR</div>
      <div style="font-size:14px;font-weight:700;color:#1A0F2E">✅ {aprobado_por}</div>
    </div>
    <p style="color:#6B5F80;font-size:12px;margin:16px 0 0">
      Cualquier consulta, escríbenos a
      <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # PDF adjunto
    attachment = MIMEBase("application", "pdf")
    attachment.set_payload(pdf_bytes)
    encoders.encode_base64(attachment)
    safe_name = (
        f"Informe_{proyecto_nombre.replace(' ', '_')}_"
        f"{periodo_display.replace(' ', '_')}.pdf"
    )
    attachment.add_header("Content-Disposition", f"attachment; filename=\"{safe_name}\"")
    msg.attach(attachment)

    # Build full recipient list (to + cc)
    recipients = [to_email]
    if cc:
        recipients.extend(cc)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, recipients, msg.as_string())
        _log_send(to_email=to_email, cc=cc, subject=subject, tipo="informe", success=True)
    except Exception as exc:
        _log_send(to_email=to_email, cc=cc, subject=subject, tipo="informe", success=False, error_msg=str(exc))
        raise


def send_alarm_notification_email(
    *,
    to_emails: list[str],
    proyecto_nombre: str,
    alarm_type: str,
    severity: str,
    details: str,
) -> None:
    """
    Send email notification for critical MGS alarms.
    Falls back silently if SMTP is not configured (logs to console).
    """
    if not settings.SMTP_HOST:
        print(
            f"[ALARM_EMAIL] SMTP not configured — alarm for {proyecto_nombre}: "
            f"{alarm_type} ({severity}) — {details}"
        )
        return

    severity_color = {"CRITICAL": "#FF3B30", "WARNING": "#FF9500", "INFO": "#34C759"}.get(severity, "#8E8E93")
    severity_label = {"CRITICAL": "CRITICA", "WARNING": "ADVERTENCIA", "INFO": "INFORMACION"}.get(severity, severity)

    subject = f"[{severity_label}] Alarma {alarm_type} — {proyecto_nombre}"
    body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:560px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Alerta de Monitoreo</div>
  </div>
  <div style="background:#F7F4FD;padding:24px 28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <div style="background:{severity_color};color:#fff;display:inline-block;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:700;letter-spacing:.5px;margin-bottom:16px">{severity_label}</div>
    <h2 style="margin:0 0 8px;font-size:18px">{proyecto_nombre}</h2>
    <p style="margin:0 0 16px;color:#6B5F80"><strong>Tipo:</strong> {alarm_type}</p>
    <div style="background:#fff;border:1px solid #EDE8F5;border-radius:8px;padding:14px 18px;margin:0 0 20px">
      <div style="font-size:11px;font-weight:700;color:#A89EC0;letter-spacing:.7px;text-transform:uppercase;margin-bottom:6px">DETALLE</div>
      <div style="font-size:14px;color:#1A0F2E">{details}</div>
    </div>
    <p style="color:#6B5F80;font-size:12px;margin:0">
      Este es un mensaje automatico del sistema de monitoreo MGS.<br>
      <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(to_emails)
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_emails, msg.as_string())
        _log_send(to_email=to_emails[0], cc=to_emails[1:] or None, subject=subject, tipo="alarma", success=True)
        print(f"[ALARM_EMAIL] Sent to {to_emails} for {proyecto_nombre}")
    except Exception as exc:
        _log_send(to_email=to_emails[0], cc=to_emails[1:] or None, subject=subject, tipo="alarma", success=False, error_msg=str(exc))
        print(f"[ALARM_EMAIL] Failed to send to {to_emails}: {exc}")
