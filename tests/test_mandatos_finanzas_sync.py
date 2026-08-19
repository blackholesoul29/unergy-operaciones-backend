"""Decisión de qué escribir en finanzas_mandatos a partir de un correo. Pura."""
from datetime import date, datetime, timezone

from app.services.mandatos.finanzas_sync import FUENTE_ENVIO, FUENTE_REVISORIA, decidir_finanzas
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
