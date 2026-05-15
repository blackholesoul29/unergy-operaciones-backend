"""
Servicio de email para envío de informes aprobados.
Usa smtplib (stdlib) + WeasyPrint para PDF.
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from app.core.config import settings


def _build_pdf(html: str) -> bytes:
    """Convierte HTML a PDF con WeasyPrint."""
    try:
        from weasyprint import HTML, CSS
        css = CSS(string="""
            @page { size: A4 portrait; margin: 12mm 14mm; }
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        """)
        return HTML(string=html, base_url=None).write_pdf(stylesheets=[css])
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint no está instalado. Agrega 'weasyprint' a requirements.txt"
        ) from exc


def send_informe_email(
    *,
    to_email: str,
    proyecto_nombre: str,
    periodo_display: str,
    aprobado_por: str,
    html_content: str,
) -> None:
    """
    Envía el informe aprobado por correo con el PDF adjunto.
    Lanza RuntimeError si SMTP no está configurado o falla el envío.
    """
    if not settings.SMTP_HOST:
        raise RuntimeError(
            "SMTP no configurado. Define SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD y SMTP_FROM en las variables de entorno."
        )

    pdf_bytes = _build_pdf(html_content)

    subject = f"Informe Operacional — {proyecto_nombre} — {periodo_display}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    body_html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:620px;margin:0 auto;padding:0">
      <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
              <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">
                Informe Operacional
              </div>
            </td>
          </tr>
        </table>
      </div>
      <div style="background:#F7F4FD;padding:24px 28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
        <p style="margin:0 0 16px">Estimado cliente,</p>
        <p style="margin:0 0 16px">
          Adjunto encontrará el <strong>Informe Operacional de {proyecto_nombre}</strong>
          correspondiente al período <strong>{periodo_display}</strong>.
        </p>
        <div style="background:#fff;border:1px solid #EDE8F5;border-radius:8px;padding:14px 18px;margin:20px 0">
          <div style="font-size:11px;font-weight:700;color:#A89EC0;letter-spacing:.7px;text-transform:uppercase;margin-bottom:6px">
            APROBADO POR
          </div>
          <div style="font-size:14px;font-weight:700;color:#1A0F2E">
            ✅ {aprobado_por}
          </div>
        </div>
        <p style="color:#6B5F80;font-size:12px;margin:16px 0 0">
          Si tiene preguntas o comentarios sobre este informe, puede responder a este correo
          o escribirnos a <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>.
        </p>
      </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # PDF adjunto
    attachment = MIMEBase("application", "pdf")
    attachment.set_payload(pdf_bytes)
    encoders.encode_base64(attachment)
    safe_name = (
        f"Informe_{proyecto_nombre.replace(' ', '_')}_{periodo_display.replace(' ', '_')}.pdf"
    )
    attachment.add_header("Content-Disposition", f"attachment; filename=\"{safe_name}\"")
    msg.attach(attachment)

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
