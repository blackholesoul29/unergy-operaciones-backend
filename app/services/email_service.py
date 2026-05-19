"""
Servicio de email para envío de informes aprobados.
Usa Playwright (Chromium headless) para generar el PDF y smtplib para enviarlo.
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from app.core.config import settings


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
    except Exception as exc:
        print(f"[OTP] Error enviando email a {to_email}: {exc} — código: {codigo}")
        raise RuntimeError(f"No se pudo enviar el código: {exc}") from exc


def send_informe_email(
    *,
    to_email: str,
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

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
