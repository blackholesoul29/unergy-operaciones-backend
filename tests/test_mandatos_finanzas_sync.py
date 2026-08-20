"""Decisión de qué escribir en finanzas_mandatos a partir de un correo. Pura."""
from types import SimpleNamespace as NS
from datetime import date, datetime, timezone

from app.services.mandatos.finanzas_sync import (
    FUENTE_ENVIO, FUENTE_REVISORIA, FUENTE_SALIENTE, _aplicar, decidir_finanzas,
)
from app.services.mandatos.imap_client import CorreoCrudo
from tests.fixtures_mandatos_correos import ENVIO_INVERSIONISTA, REVISORIA_SEGUIMIENTO

AHORA = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
PDF_FIRMADO = b"%PDF-firmado"
PDF_SIN = b"%PDF-sin"


def _correo(cuerpo, adjuntos=(), asunto="Certificados junio 2026", remitente="x@y.com"):
    return CorreoCrudo(message_id="<t@test>", fecha=AHORA, remitente=remitente,
                       asunto=asunto, cuerpo=cuerpo, adjuntos=list(adjuntos))


def _firmas_fake(resultado):
    return lambda _contenido: {"lineas": 2, "firmadas": 2 if resultado else 0,
                               "estado": "firmado_completo" if resultado else "sin_firmas"}


def test_pdf_firmado_de_la_revisoria_da_firmado():
    c = _correo("Adjunto los certificados firmados.",
                [("CMU1140-Mandato-Costos-Minigranja Solar Merengue.pdf", PDF_FIRMADO)])
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(True))
    assert len(d["acciones"]) == 1
    a = d["acciones"][0]
    assert a["estado"] == "firmado"
    assert a["cmu"] == "CMU1140"
    assert a["proyecto"] == "Minigranja Solar Merengue"
    assert a["tipo"] == "costo"


def test_pdf_sin_firmas_no_se_marca_firmado():
    """El PDF llegó, pero abrirlo dice que no está firmado. Manda el documento,
    no el hecho de que haya adjunto."""
    c = _correo("Adjunto.", [("CMU1140-Mandato-Costos-X.pdf", PDF_SIN)])
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(False))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_correo_de_seguimiento_no_se_interpreta():
    c = _correo(REVISORIA_SEGUIMIENTO)
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(True))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_envio_a_inversionista_usa_el_pa_del_cuerpo_como_tercero():
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    a = d["acciones"][0]
    assert a["estado"] == "enviado_inversionista"
    assert a["tercero"] == "P.A SOL DE LA SIERRA"
    assert a["periodo"] == date(2026, 6, 1)


def test_sin_pa_en_el_cuerpo_no_se_inventa_identidad():
    """Sin tercero no hay identidad completa. Antes que adivinar, se marca para
    revisión: una identidad equivocada crea una fila fantasma que nadie limpia."""
    c = _correo("Adjunto los certificados de junio.",
                [("CMU1135-Mandato-Costos-X.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_sin_periodo_en_el_asunto_no_se_inventa():
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-X.pdf", PDF_FIRMADO)],
                asunto="RE: sin mes", remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert d["acciones"] == []


class _DBFake:
    """Sesión mínima: devuelve la fila que se le configure."""

    def __init__(self, fila):
        self._fila = fila

    def query(self, _modelo):
        return self

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._fila


def test_reaplicar_el_mismo_estado_no_es_error():
    """Caso real: 40 de 61 acciones de la primera tanda eran firmado→firmado.

    Volver a recibir el PDF firmado de un mandato ya firmado es idempotencia,
    no un conflicto. Reportarlo como transicion_invalida llena el panel de
    revisión de ruido y esconde los conflictos reales.
    """
    fila = NS(id=7, cmu="CMU1270", estado="firmado", periodo=None, tipo="costo",
              drive_url="https://drive/x", comentario=None, correo_ref=None,
              fecha_firma=None)
    accion = {"cmu": "CMU1270", "estado": "firmado", "periodo": None,
              "adjunto": None, "comentario": None}
    correo = NS(message_id="<x@test>", fecha=AHORA, adjuntos=[])
    r = _aplicar(_DBFake(fila), accion, correo)
    assert r["resultado"] == "sin_cambio"
    assert fila.estado == "firmado"


def test_saliente_registra_el_envio_aunque_el_pdf_no_este_firmado():
    """Un mandato que va HACIA la revisoría está sin firmar por definición --
    justamente se manda para que lo firmen. Antes esto no producía nada y la
    reconciliación se quedaba sin denominador."""
    c = _correo("Adjunto los mandatos de julio para revisión.",
                [("CMU1255-Mandato-Costos-Minigranja Solar Esmeralda-STRADA ASOCIADOS S A S.pdf",
                  PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert len(d["acciones"]) == 1
    a = d["acciones"][0]
    assert a["estado"] == "sin_firma"
    assert a["cmu"] == "CMU1255"
    assert a["tercero"] == "STRADA ASOCIADOS S A S"


def test_saliente_ignora_adjuntos_que_no_son_mandato():
    c = _correo("Adjunto.", [("Liquidacion_CoxEnergy_Jul2026.pdf", PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []


def test_saliente_sin_periodo_en_el_asunto_no_inventa():
    c = _correo("Adjunto.",
                [("CMU1255-Mandato-Costos-Esmeralda-STRADA ASOCIADOS S A S.pdf", PDF_SIN)],
                asunto="Re: sin mes")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []


# ── buzones múltiples ─────────────────────────────────────────────────────────

def test_buzones_lista_los_configurados(monkeypatch):
    """Parte del correo de mandatos no pasa por adhara@: algunos envíos a la
    revisoría salen de la cuenta de Jessica y viven en SU carpeta de Enviados.
    Sin leer ese buzón, la reconciliación nunca sabe que salieron."""
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER", "adhara@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD", "x")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER_2", "jessica@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD_2", "y")
    assert buzones() == [("adhara@unergy.io", "x"), ("jessica@unergy.io", "y")]


def test_buzones_omite_el_segundo_si_no_esta_configurado(monkeypatch):
    """El segundo buzón es opcional: sin él todo funciona igual, solo con
    menos cobertura."""
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER", "adhara@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD", "x")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER_2", "")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD_2", "")
    assert buzones() == [("adhara@unergy.io", "x")]


def test_buzones_vacio_sin_credenciales(monkeypatch):
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    for k in ("MANDATOS_IMAP_USER", "MANDATOS_IMAP_PASSWORD",
              "MANDATOS_IMAP_USER_2", "MANDATOS_IMAP_PASSWORD_2"):
        monkeypatch.setattr(settings, k, "")
    assert buzones() == []


def test_segundo_buzon_reusa_smtp_password_si_es_la_misma_cuenta(monkeypatch):
    """Sin duplicar el secreto: si el segundo buzón ES la cuenta de envío, se
    reusa SMTP_PASSWORD. Dos copias de la misma contraseña se desincronizan al
    rotarla y una de las dos deja de servir sin que nadie lo note."""
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER", "adhara@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD", "clave-adhara")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER_2", "operaciones@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD_2", "")
    monkeypatch.setattr(settings, "SMTP_USER", "operaciones@unergy.io")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "clave-operaciones")
    assert buzones() == [("adhara@unergy.io", "clave-adhara"),
                         ("operaciones@unergy.io", "clave-operaciones")]


def test_no_hereda_la_cuenta_de_envio_si_cambio(monkeypatch):
    """El fallback exige que el usuario coincida. Si alguien mueve el envío a
    otra dirección, el buzón se omite y el log lo dice -- en vez de ponerse a
    leer calladito una cuenta que nadie eligió."""
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER", "adhara@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD", "clave-adhara")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER_2", "operaciones@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD_2", "")
    monkeypatch.setattr(settings, "SMTP_USER", "noreply@unergy.io")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "clave-de-otra-cuenta")
    assert buzones() == [("adhara@unergy.io", "clave-adhara")]


def test_password_propia_del_segundo_buzon_manda_sobre_el_fallback(monkeypatch):
    from app.core.config import settings
    from app.services.mandatos.imap_client import buzones

    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER", "adhara@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD", "clave-adhara")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_USER_2", "operaciones@unergy.io")
    monkeypatch.setattr(settings, "MANDATOS_IMAP_PASSWORD_2", "clave-propia")
    monkeypatch.setattr(settings, "SMTP_USER", "operaciones@unergy.io")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "clave-smtp")
    assert buzones()[1] == ("operaciones@unergy.io", "clave-propia")


# ── clasificación por destino ─────────────────────────────────────────────────

def test_correo_de_jessica_hacia_la_revisoria_es_un_envio():
    """Caso real: 'Revisión de mandatos autoconsumo - Julio', mandado por Jessica
    a Vanessa con copia a Adhara. Llega al INBOX como correo de Jessica, así que
    antes se trataba como envío a inversionista y su envío nunca se registraba
    -- 80 CMU de julio quedaron sin denominador por esto."""
    c = _correo("Adjunto los mandatos de autoconsumo para revisión.",
                [("CMU1182-Mandato-Iml Empaques Colombia Sas-Ayurá S.A.S.pdf", PDF_SIN)],
                asunto="Revisión de mandatos autoconsumo - Julio",
                remitente="jessica@unergy.io")
    c.destinatarios = "vlondono@jbp.com.co, adhara@unergy.io"
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(False))
    assert [a["estado"] for a in d["acciones"]] == ["sin_firma"]


def test_correo_de_jessica_a_un_inversionista_sigue_siendo_envio():
    """Sin la revisoría entre destinatarios, se comporta como antes."""
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz-Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    c.destinatarios = "juliana@solenium.co, adhara@unergy.io"
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert [a["estado"] for a in d["acciones"]] == ["enviado_inversionista"]


def test_sin_destinatarios_se_comporta_como_antes():
    """Los correos ya registrados no traen destinatarios. No deben cambiar de
    interpretación solo porque el campo llegue vacío."""
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz-Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert [a["estado"] for a in d["acciones"]] == ["enviado_inversionista"]


# ── estado `corregido` ────────────────────────────────────────────────────────

def test_un_correo_de_correcciones_marca_corregido():
    """Confirmado con el usuario: la corrección aplica a los CMU que el correo
    nombra. Sin esto, con_comentarios era un callejón sin salida -- nada emitía
    `corregido`, así que un mandato observado no podía volver a firmarse."""
    c = _correo("Hola Vanessa, te comparto los mandatos con correcciones: "
                "CMU1255, CMU1266 y CMU1270.",
                asunto="Re: Revisión mandatos de costos - Julio",
                remitente="adhara@unergy.io")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert sorted(a["cmu"] for a in d["acciones"]) == ["CMU1255", "CMU1266", "CMU1270"]
    assert all(a["estado"] == "corregido" for a in d["acciones"])


def test_un_saliente_sin_lenguaje_de_correccion_no_marca_corregido():
    c = _correo("Adjunto los mandatos de julio para su revisión.",
                [("CMU1255-Mandato-Costos-Esmeralda-STRADA ASOCIADOS S A S.pdf", PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert [a["estado"] for a in d["acciones"]] == ["sin_firma"]


def test_correcciones_sin_cmu_nombrado_no_inventa():
    """Si el correo dice que comparte correcciones pero no nombra ninguno, no se
    adivina a cuáles aplica: se deja para revisión."""
    c = _correo("Te comparto los mandatos con correcciones.",
                asunto="Re: Revisión mandatos de costos - Julio")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_correcciones_no_toca_los_cmu_citados_del_hilo():
    """El correo de correcciones casi siempre responde al que traía las
    observaciones. Sin recortar la cita se marcarían como corregidos CMU que
    solo aparecen en el historial del hilo."""
    c = _correo("Te comparto las correcciones de CMU1255.\n"
                "> CMU1266 no se evidencia contabilizacion\n"
                "> CMU1270 diferencia en el arriendo\n",
                asunto="Re: Revisión mandatos de costos - Julio")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert [a["cmu"] for a in d["acciones"]] == ["CMU1255"]
