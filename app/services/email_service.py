"""
Servicio de email para envío de informes aprobados.
Usa únicamente smtplib de la stdlib — sin dependencias externas.
El informe se envía como HTML en el cuerpo del correo.
"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


def send_informe_email(
    *,
    to_email: str,
    proyecto_nombre: str,
    periodo_display: str,
    aprobado_por: str,
    html_content: str,
) -> None:
    """
    Envía el informe aprobado por correo.
    El informe completo va en el cuerpo del email como HTML.
    Lanza RuntimeError si SMTP no está configurado o falla el envío.
    """
    if not settings.SMTP_HOST:
        raise RuntimeError(
            "SMTP no configurado. Define SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD y SMTP_FROM en las variables de entorno."
        )

    subject = f"Informe Operacional — {proyecto_nombre} — {periodo_display}"

    # Cabecera de presentación + informe completo embebido
    intro = f"""
    <div style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:800px;margin:0 auto 0">
      <div style="background:#1A0F2E;padding:20px 28px;border-radius:10px 10px 0 0;display:flex;align-items:center;gap:16px">
        <div>
          <div style="color:#F6FF72;font-size:18px;font-weight:800;letter-spacing:1px">UNERGY</div>
          <div style="color:#6B5F80;font-size:10px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">Informe Operacional</div>
        </div>
        <div style="margin-left:auto;background:#4ADE8020;border:1px solid #4ADE8060;border-radius:8px;padding:6px 14px">
          <div style="font-size:10px;color:#2D8A4E;font-weight:700">✅ APROBADO POR</div>
          <div style="font-size:13px;color:#1A0F2E;font-weight:800">{aprobado_por}</div>
        </div>
      </div>
      <div style="background:#F0EBF8;padding:12px 28px;border:1px solid #EDE8F5;border-top:none;font-size:12px;color:#6B5F80">
        Estimado cliente, a continuación encontrará el <strong>Informe Operacional de {proyecto_nombre}</strong>
        correspondiente al período <strong>{periodo_display}</strong>.
        Para imprimir o guardar como PDF, use <em>Archivo → Imprimir → Guardar como PDF</em> en su navegador.
      </div>
    </div>
    """

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe {proyecto_nombre} — {periodo_display}</title>
</head>
<body style="margin:0;padding:16px;background:#f4f0fc;font-family:'Segoe UI',Arial,sans-serif">
{intro}
<div style="max-width:800px;margin:0 auto">
{html_content}
</div>
<div style="max-width:800px;margin:8px auto;text-align:center;font-size:10px;color:#A89EC0;padding:12px">
  UNERGY ENERGÍA DIGITAL S.A.S ESP · operaciones@unergy.io · www.unergy.co
</div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
