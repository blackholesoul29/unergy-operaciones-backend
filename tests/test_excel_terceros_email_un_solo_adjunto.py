"""revisar_correo_cedillanos() (excel_terceros_email.py) -- aplica SOLO el
primer adjunto que cargue con éxito, no todos los que traiga el correo.

El docstring siempre dijo "aplica el primer adjunto Excel que cargue con
éxito", pero el loop no tenía `break` -- con más de un adjunto válido en el
mismo correo (no debería pasar, pero si pasara), el último aplicado pisaba
en silencio lo que ya había cargado el anterior para las mismas fechas
(auditoría Reporte ASIC 2026-08-26)."""
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

import app.services.reporte_energia.excel_terceros_email as mod


class _FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _FakeIMAP:
    def __init__(self, mensaje_bytes):
        self._mensaje_bytes = mensaje_bytes
        self.marcado_leido = []
        self.criterios_buscados = []

    def login(self, user, password):
        pass

    def select(self, mailbox):
        pass

    def search(self, charset, criterio):
        self.criterios_buscados.append(criterio)
        return "OK", [b"1"]

    def fetch(self, msg_id, spec):
        return "OK", [(b"1", self._mensaje_bytes)]

    def store(self, msg_id, flags, valor):
        self.marcado_leido.append(msg_id)

    def close(self):
        pass

    def logout(self):
        pass


def _correo_con_adjuntos(nombres: list[str]) -> bytes:
    msg = MIMEMultipart()
    msg["From"] = f"cgm@{mod.CEDILLANOS_DOMINIO_REMITENTE}"
    msg["Subject"] = f"RE: {mod.CEDILLANOS_ASUNTO_CLAVE} - Alsec Llanos"
    for nombre in nombres:
        parte = MIMEApplication(b"contenido-fake", _subtype="xlsx")
        parte.add_header("Content-Disposition", "attachment", filename=nombre)
        msg.attach(parte)
    return msg.as_bytes()


def test_dos_adjuntos_validos_solo_aplica_el_primero(monkeypatch):
    mensaje = _correo_con_adjuntos(["reporte_a.xlsx", "reporte_b.xlsx"])
    fake_imap = _FakeIMAP(mensaje)
    fake_db = _FakeDB()

    monkeypatch.setattr(mod.settings, "SMTP_USER", "user@test.com")
    monkeypatch.setattr(mod.settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: fake_imap)
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)

    llamadas = []

    def _fake_aplicar(db, frontera_id, contenido):
        llamadas.append(contenido)
        from datetime import date
        return [date(2026, 8, 25)]

    monkeypatch.setattr(mod, "aplicar_excel_terceros", _fake_aplicar)

    mod.revisar_correo_cedillanos()

    assert len(llamadas) == 1  # nunca se llegó a procesar el segundo adjunto
    assert fake_db.commits == 1
    assert fake_imap.marcado_leido == [b"1"]


def test_primer_adjunto_invalido_cae_al_segundo(monkeypatch):
    """Si el primero falla (formato inesperado / sin filas válidas), sí debe
    seguir probando los siguientes -- el break es solo tras un ÉXITO."""
    mensaje = _correo_con_adjuntos(["malo.xlsx", "bueno.xlsx"])
    fake_imap = _FakeIMAP(mensaje)
    fake_db = _FakeDB()

    monkeypatch.setattr(mod.settings, "SMTP_USER", "user@test.com")
    monkeypatch.setattr(mod.settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: fake_imap)
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)

    llamadas = {"n": 0}

    def _fake_aplicar_ordenado(db, frontera_id, contenido):
        llamadas["n"] += 1
        from datetime import date
        if llamadas["n"] == 1:
            raise ValueError("formato inesperado")
        return [date(2026, 8, 25)]

    monkeypatch.setattr(mod, "aplicar_excel_terceros", _fake_aplicar_ordenado)

    mod.revisar_correo_cedillanos()

    assert llamadas["n"] == 2  # probó el primero (falló), luego el segundo (éxito)
    assert fake_db.commits == 1
    assert fake_imap.marcado_leido == [b"1"]


def test_busca_por_dominio_no_por_casilla_exacta(monkeypatch):
    """Bug real 2026-08-27: el correo diario no siempre lo manda la misma
    casilla -- ese día lo mandó otra persona del mismo dominio/hilo
    (jgonzaleso@erco.energy en vez de cgm@erco.energy) y el filtro por
    remitente EXACTO hizo que las 9 corridas entre 4-6am no encontraran el
    correo, sin ningún error visible (una búsqueda sin resultados es una
    corrida válida). El criterio de búsqueda debe anclarse al dominio, no a
    una casilla puntual."""
    mensaje = _correo_con_adjuntos(["reporte.xlsx"])
    fake_imap = _FakeIMAP(mensaje)
    fake_db = _FakeDB()

    monkeypatch.setattr(mod.settings, "SMTP_USER", "user@test.com")
    monkeypatch.setattr(mod.settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: fake_imap)
    monkeypatch.setattr(mod, "SessionLocal", lambda: fake_db)

    from datetime import date
    monkeypatch.setattr(mod, "aplicar_excel_terceros", lambda db, fid, contenido: [date(2026, 8, 25)])

    mod.revisar_correo_cedillanos()

    assert len(fake_imap.criterios_buscados) == 1
    criterio = fake_imap.criterios_buscados[0]
    assert mod.CEDILLANOS_DOMINIO_REMITENTE in criterio
    assert "cgm@erco.energy" not in criterio, "no debe anclarse a una casilla puntual, cualquier remitente del dominio debe hacer match"
