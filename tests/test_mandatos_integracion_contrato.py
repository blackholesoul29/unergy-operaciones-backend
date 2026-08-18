"""Contrato entre los dos módulos de Mandatos, verificado con correos reales.

Contexto: existen dos sistemas que leen los mismos correos de la revisoría --
`finanzas_mandatos` (Jessica, en producción, alimentado por un script local) y
`mandatos` Fase B (cron IMAP en la plataforma). La propuesta de integración usa
el esquema y el parsing de Finanzas como destino, y el motor de lectura de
Fase B como fuente. Ver
docs/superpowers/specs/2026-08-18-mandatos-integracion-design.md

Estos tests fijan qué hace HOY el parser de Finanzas cuando se le pasan los
adjuntos y asuntos reales que ve el cron de Fase B. No prueban código nuevo:
documentan el contrato entre las dos piezas, para que la integración se diseñe
sobre comportamiento medido y no sobre suposiciones, y para que un cambio en el
parser de Finanzas que rompa al cron se note acá.
"""
from datetime import date

import pytest

from app.services import finanzas_mandatos_service as svc
from tests.fixtures_mandatos_correos import ENVIO_INVERSIONISTA_ADJUNTOS


# ── El parser de Finanzas sí entiende los adjuntos reales de Jessica ──────────

PDFS_REALES = [n for n in ENVIO_INVERSIONISTA_ADJUNTOS if n.lower().endswith(".pdf")]


@pytest.mark.parametrize("nombre", PDFS_REALES)
def test_adjuntos_reales_rinden_identidad_completa(nombre):
    """Los cuatro PDFs del correo del 12 ago dan (tipo, cmu, proyecto, tercero)."""
    tipo = svc.tipo_de_nombre(nombre)
    proyecto, tercero = svc.parsear_proyecto_tercero(nombre, tipo)
    assert tipo == "costo"
    assert svc.extraer_cmu(nombre) is not None
    assert proyecto == "Sol de la Sierra"
    assert tercero == "Bancolombia"


def test_cada_pdf_real_da_su_propio_cmu():
    cmus = [svc.extraer_cmu(n) for n in PDFS_REALES]
    assert cmus == ["CMU1135", "CMU1141", "CMU1139", "CMU1142"]


def test_periodo_sale_del_asunto_con_anio_explicito():
    assert svc.extraer_periodo_de_asunto(
        "certificados de mandato junio 2026", date(2026, 8, 18)) == date(2026, 6, 1)


def test_periodo_infiere_el_anio_del_correo_cuando_el_asunto_no_lo_trae():
    assert svc.extraer_periodo_de_asunto(
        "Mandatos de costos julio", date(2026, 8, 18)) == date(2026, 7, 1)


def test_asunto_sin_mes_no_inventa_periodo():
    assert svc.extraer_periodo_de_asunto("RE: FRT85329", date(2026, 8, 18)) is None


# ── El peligro: tipo_de_nombre nunca dice "no sé" ─────────────────────────────

@pytest.mark.parametrize("nombre", [
    "REGISTRO MANDATOS.xlsx",
    "factura_luz.pdf",
    "",
])
def test_tipo_de_nombre_cae_en_ingreso_para_archivos_que_no_son_mandato(nombre):
    """Fija el comportamiento actual, que NO es seguro para la integración.

    `tipo_de_nombre` devuelve 'ingreso' para todo lo que no diga literalmente
    'mandato-costos'. En el flujo de Jessica eso es inofensivo: su script local
    solo le entrega adjuntos que ya sabe que son mandatos. Pero el cron de
    Fase B ve TODOS los adjuntos del correo, así que un archivo suelto entraría
    como mandato de ingreso y crearía una fila basura con identidad inventada.

    Conclusión para la integración: el adaptador debe decidir por sí mismo si un
    adjunto es un mandato ANTES de preguntarle el tipo a esta función -- no puede
    delegarle esa decisión, porque esta función no tiene forma de responder "no
    es un mandato".
    """
    assert svc.tipo_de_nombre(nombre) == "ingreso"


def test_el_excel_del_correo_real_seria_ingerido_como_mandato():
    """El correo del 12 ago trae 'REGISTRO MANDATOS.xlsx' junto a los PDFs.

    Caso concreto del riesgo anterior, con un archivo que de verdad llega.
    """
    nombre = "REGISTRO MANDATOS.xlsx"
    assert nombre in ENVIO_INVERSIONISTA_ADJUNTOS
    tipo = svc.tipo_de_nombre(nombre)
    proyecto, tercero = svc.parsear_proyecto_tercero(nombre, tipo)
    assert (tipo, proyecto, tercero) == ("ingreso", "REGISTRO MANDATOS.xlsx", "")
    assert svc.extraer_cmu(nombre) is None
