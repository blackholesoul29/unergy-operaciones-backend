"""Tests de la decisión de sincronización -- pura, sin BD ni IMAP.

decidir_acciones() concentra las reglas de negocio del spec §6.4 y se prueba
sola; aplicar_correo() (que sí toca la BD) queda cubierto por el uso real.
"""
from datetime import datetime, timezone

from app.services.mandatos.email_sync import decidir_acciones, FUENTE_REVISORIA, FUENTE_ENVIO
from app.services.mandatos.imap_client import CorreoCrudo
from tests.fixtures_mandatos_correos import (
    REVISORIA_OBSERVACIONES, REVISORIA_SEGUIMIENTO, REVISORIA_MIXTO,
    ENVIO_INVERSIONISTA, ENVIO_INVERSIONISTA_ADJUNTOS,
    LIQUIDACION_PRELIMINAR, LIQUIDACION_PRELIMINAR_ADJUNTOS,
)

AHORA = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)


def _correo(cuerpo, adjuntos=(), asunto="Certificados", remitente="vlondono@jbp.com.co"):
    return CorreoCrudo(
        message_id=f"<{hash(cuerpo)}@test>", fecha=AHORA, remitente=remitente,
        asunto=asunto, cuerpo=cuerpo,
        adjuntos=[(n, b"%PDF-1.4 fake") for n in adjuntos],
    )


def test_observaciones_producen_con_correcciones():
    d = decidir_acciones(_correo(REVISORIA_OBSERVACIONES), FUENTE_REVISORIA)
    assert d["clasificacion"] == "molde_simple"
    assert [a["cmu"] for a in d["acciones"]] == [
        "CMU1255", "CMU1266", "CMU1269", "CMU1270", "CMU1271", "CMU1284",
    ]
    assert all(a["estado_destino"] == "con_correcciones" for a in d["acciones"])


def test_seguimiento_no_produce_acciones_de_texto():
    """El correo donde CMU1255 quedó resuelto: cero acciones, revisión manual."""
    d = decidir_acciones(_correo(REVISORIA_SEGUIMIENTO), FUENTE_REVISORIA)
    assert d["clasificacion"] == "seguimiento"
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_seguimiento_con_pdf_igual_procesa_el_adjunto():
    """La compuerta gobierna el texto, no los adjuntos (spec §6.3)."""
    d = decidir_acciones(
        _correo(REVISORIA_SEGUIMIENTO, adjuntos=["CMU1266-firmado.pdf"]), FUENTE_REVISORIA
    )
    assert [a["cmu"] for a in d["acciones"]] == ["CMU1266"]
    assert d["acciones"][0]["estado_destino"] == "firmado"
    assert d["requiere_revision"] is True


def test_correo_mixto_produce_correcciones_y_firmados():
    d = decidir_acciones(
        _correo(REVISORIA_MIXTO, adjuntos=["CMU1052-Mandato-Costos-Sol-X.pdf"]),
        FUENTE_REVISORIA,
    )
    por_cmu = {a["cmu"]: a["estado_destino"] for a in d["acciones"]}
    assert por_cmu["CMU1122"] == "con_correcciones"
    assert por_cmu["CMU1052"] == "firmado"      # el adjunto manda sobre el texto


def test_envio_a_inversionista_desde_los_adjuntos():
    d = decidir_acciones(
        _correo(ENVIO_INVERSIONISTA, adjuntos=ENVIO_INVERSIONISTA_ADJUNTOS,
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert sorted(a["cmu"] for a in d["acciones"]) == [
        "CMU1135", "CMU1139", "CMU1141", "CMU1142",
    ]
    assert all(a["estado_destino"] == "enviado_inversionista" for a in d["acciones"])


def test_liquidacion_preliminar_no_produce_nada():
    """Caso negativo: menciona 'certificados de mandato' pero no trae adjuntos."""
    d = decidir_acciones(
        _correo(LIQUIDACION_PRELIMINAR, adjuntos=LIQUIDACION_PRELIMINAR_ADJUNTOS,
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert d["acciones"] == []
    assert d["requiere_revision"] is False      # nada que revisar: no era un envío


def test_envio_ignora_adjuntos_que_no_son_pdf_de_mandato():
    d = decidir_acciones(
        _correo(ENVIO_INVERSIONISTA, adjuntos=["REGISTRO MANDATOS.xlsx"],
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert d["acciones"] == []
