"""email_service.py -- cada _log_send() debe reflejar TODOS los destinatarios
reales, no solo to_emails[0], y las funciones que ya conocen un id real
(cliente/operador/proyecto) deben pasarlo a _log_send() -- auditoría de
envío de correos 2026-08-26. Antes, send_informe_email/send_alarm_
notification_email/send_reporte_cgm_email solo dejaban en email_envios el
primer destinatario; el resto se perdía sin dejar rastro."""
from app.core.config import settings
from app.services import email_service


def _sin_smtp_real(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_service, "_smtp_send", lambda msg, recipients: None)


def test_send_informe_email_loguea_todos_los_destinatarios_y_proyecto_id(monkeypatch):
    _sin_smtp_real(monkeypatch)
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    email_service.send_informe_email(
        to_emails=["a@test.com", "b@test.com"],
        proyecto_nombre="Test", periodo_display="Agosto 2026",
        aprobado_por="Alguien", html_content="<p>hola</p>",
        proyecto_id=42,
    )

    assert len(llamadas) == 2
    assert {c["to_email"] for c in llamadas} == {"a@test.com", "b@test.com"}
    assert all(c["proyecto_id"] == 42 and c["success"] is True for c in llamadas)


def test_send_alarm_notification_email_loguea_todos_los_destinatarios(monkeypatch):
    _sin_smtp_real(monkeypatch)
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    email_service.send_alarm_notification_email(
        to_emails=["a@test.com", "b@test.com", "c@test.com"],
        proyecto_nombre="Test", alarm_type="Falla", severity="CRITICAL", details="detalle",
    )

    assert len(llamadas) == 3
    assert {c["to_email"] for c in llamadas} == {"a@test.com", "b@test.com", "c@test.com"}
    # antes, b y c quedaban metidos en "cc" del primero -- ahora cada uno es su propia fila
    assert all(c["cc"] is None for c in llamadas)


def test_send_reporte_cgm_email_loguea_todos_los_destinatarios_y_fks(monkeypatch):
    _sin_smtp_real(monkeypatch)
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    email_service.send_reporte_cgm_email(
        to_emails=["a@test.com", "b@test.com"],
        excel_bytes=b"fake", filename="reporte.xlsx", fecha_str="2026-08-25",
        destinatario_nombre="Cliente Test", cliente_id=99, operador_red_id=None,
    )

    assert len(llamadas) == 2
    assert {c["to_email"] for c in llamadas} == {"a@test.com", "b@test.com"}
    assert all(c["cliente_id"] == 99 and c["operador_red_id"] is None for c in llamadas)


def test_send_falla_notification_email_pasa_proyecto_id(monkeypatch):
    _sin_smtp_real(monkeypatch)
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    email_service.send_falla_notification_email(
        to_emails=["a@test.com"], codigo_falla="F-001", proyecto_nombre="Test",
        descripcion="desc", estado_etiqueta="Abierta", prioridad_etiqueta="Alta",
        fecha_identificacion="2026-08-25", asignado_a=None, registrado_por="Alguien",
        proyecto_id=7,
    )

    assert len(llamadas) == 1
    assert llamadas[0]["proyecto_id"] == 7


def test_send_reset_password_email_ahora_si_loguea(monkeypatch):
    """Finding #1 de la auditoría -- era la única función de las 8 que no
    llamaba a _log_send(), un flujo sensible (reset de contraseña) sin
    ningún rastro en email_envios."""
    _sin_smtp_real(monkeypatch)
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    email_service.send_reset_password_email(to_email="a@test.com", token="tok123")

    assert len(llamadas) == 1
    assert llamadas[0]["to_email"] == "a@test.com"
    assert llamadas[0]["tipo"] == "reset_password"
    assert llamadas[0]["success"] is True


def test_send_reset_password_email_loguea_el_fallo_tambien(monkeypatch):
    _sin_smtp_real(monkeypatch)
    monkeypatch.setattr(email_service, "_smtp_send", lambda msg, recipients: (_ for _ in ()).throw(RuntimeError("smtp caído")))
    llamadas = []
    monkeypatch.setattr(email_service, "_log_send", lambda **kw: llamadas.append(kw))

    try:
        email_service.send_reset_password_email(to_email="a@test.com", token="tok123")
    except RuntimeError:
        pass

    assert len(llamadas) == 1
    assert llamadas[0]["success"] is False
    assert "smtp caído" in llamadas[0]["error_msg"]


def test_send_otp_email_ya_no_existe():
    """Finding #3 de la auditoría -- código muerto, cero llamadores en todo
    el repo (nunca existió una ruta/feature de OTP real)."""
    assert not hasattr(email_service, "send_otp_email")
