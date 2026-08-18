"""Tests de la decisión de sincronización -- pura, sin BD ni IMAP.

decidir_acciones() concentra las reglas de negocio del spec §6.4 y se prueba
sola; lo mismo para elegir_mandato() y planear_transicion(), que son las dos
decisiones riesgosas que antes vivían enredadas dentro de _aplicar_accion()
(la parte que sí toca la BD, cubierta por el uso real, no por estos tests).
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services.mandatos.email_sync import (
    decidir_acciones, elegir_mandato, planear_transicion, _guardar_adjunto,
    FUENTE_REVISORIA, FUENTE_ENVIO,
)
from app.services.mandatos.imap_client import CorreoCrudo
from tests.fixtures_mandatos_correos import (
    REVISORIA_OBSERVACIONES, REVISORIA_SEGUIMIENTO, REVISORIA_MIXTO,
    ADJUNTOS_REALES_DRIVE, ENVIO_INVERSIONISTA,
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
        _correo(ENVIO_INVERSIONISTA, adjuntos=ADJUNTOS_REALES_DRIVE,
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert sorted(a["cmu"] for a in d["acciones"]) == [
        "CMU1135", "CMU1140", "CMU1147", "CMU1148",
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


# ── elegir_mandato ───────────────────────────────────────────────────────────

def _mandato(id_, periodo, estado):
    return SimpleNamespace(id=id_, cmu="CMU1255", periodo=periodo, estado=estado)


def test_elegir_mandato_un_no_terminal_se_elige_sin_ambiguedad():
    julio = _mandato(1, date(2026, 7, 1), "enviado_inversionista")   # terminal
    agosto = _mandato(2, date(2026, 8, 1), "enviado_revisoria")       # no terminal
    m, motivo = elegir_mandato([julio, agosto])
    assert m is agosto
    assert motivo is None


def test_elegir_mandato_dos_no_terminales_es_ambiguo():
    """El bug real: julio con_correcciones y agosto enviado_revisoria a la vez --
    no hay forma de saber a cuál se refiere una corrección tardía sin período."""
    julio = _mandato(1, date(2026, 7, 1), "con_correcciones")
    agosto = _mandato(2, date(2026, 8, 1), "enviado_revisoria")
    m, motivo = elegir_mandato([julio, agosto])
    assert m is None
    assert motivo == "periodo_ambiguo"


def test_elegir_mandato_sin_candidatos_no_encontrado():
    m, motivo = elegir_mandato([])
    assert m is None
    assert motivo == "cmu_no_encontrado"


def test_elegir_mandato_todos_terminales_devuelve_el_mas_reciente():
    julio = _mandato(1, date(2026, 7, 1), "enviado_inversionista")
    agosto = _mandato(2, date(2026, 8, 1), "enviado_inversionista")
    m, motivo = elegir_mandato([julio, agosto])
    assert m is agosto
    assert motivo is None


# ── planear_transicion ───────────────────────────────────────────────────────

def test_planear_transicion_encadena_firmado_desde_enviado_revisoria():
    assert planear_transicion("enviado_revisoria", "enviado_inversionista") == [
        "firmado", "enviado_inversionista",
    ]


def test_planear_transicion_encadena_firmado_desde_corregido():
    assert planear_transicion("corregido", "enviado_inversionista") == [
        "firmado", "enviado_inversionista",
    ]


def test_planear_transicion_con_correcciones_no_encadena():
    """La anomalía que debe verse, no resolverse sola: enviarle al inversionista
    un mandato con observaciones abiertas nunca se aplica automáticamente."""
    assert planear_transicion("con_correcciones", "enviado_inversionista") is None


def test_planear_transicion_un_paso_normal():
    assert planear_transicion("enviado_revisoria", "con_correcciones") == ["con_correcciones"]


def test_planear_transicion_par_invalido_devuelve_none():
    assert planear_transicion("enviado_inversionista", "firmado") is None


# ── _guardar_adjunto: saneamiento de ruta ────────────────────────────────────

def test_guardar_adjunto_bloquea_path_traversal(tmp_path, monkeypatch):
    """Un nombre de adjunto con '../' no debe poder escribir fuera de _PDF_DIR --
    mismo criterio que asociar_pdf() en app/api/v1/mandatos.py."""
    import app.services.mandatos.email_sync as email_sync

    pdf_dir = tmp_path / "uploads" / "mandatos"
    fuera = tmp_path / "fuera_del_directorio.pdf"
    monkeypatch.setattr(email_sync, "_PDF_DIR", pdf_dir)

    nombre_malicioso = "../../../fuera_del_directorio.pdf"
    resultado = email_sync._guardar_adjunto(nombre_malicioso, b"%PDF-1.4 fake")

    assert resultado is not None                 # se guarda, pero saneado
    assert not fuera.exists()                    # nunca escribe fuera de _PDF_DIR
    guardado = pdf_dir / "fuera_del_directorio.pdf"
    assert guardado.is_file()
    assert guardado.read_bytes() == b"%PDF-1.4 fake"


def test_guardar_adjunto_nombre_normal_se_guarda_dentro_del_directorio(tmp_path, monkeypatch):
    import app.services.mandatos.email_sync as email_sync

    pdf_dir = tmp_path / "uploads" / "mandatos"
    monkeypatch.setattr(email_sync, "_PDF_DIR", pdf_dir)

    resultado = email_sync._guardar_adjunto("CMU1255-Mandato-Costos.pdf", b"%PDF-1.4 fake")

    assert resultado == str(pdf_dir / "CMU1255-Mandato-Costos.pdf")
    assert (pdf_dir / "CMU1255-Mandato-Costos.pdf").read_bytes() == b"%PDF-1.4 fake"
