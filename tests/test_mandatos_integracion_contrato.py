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
from app.services.mandatos_service import parsear_nombre_zip
from tests.fixtures_mandatos_correos import (
    ADJUNTOS_REALES_DRIVE, ENVIO_INVERSIONISTA_ADJUNTOS,
)


# ── Qué SÍ sale del nombre del archivo ────────────────────────────────────────

@pytest.mark.parametrize("nombre", ADJUNTOS_REALES_DRIVE)
def test_del_nombre_salen_tipo_cmu_y_proyecto(nombre):
    tipo = svc.tipo_de_nombre(nombre)
    proyecto, _ = svc.parsear_proyecto_tercero(nombre, tipo)
    assert tipo == "costo"
    assert svc.extraer_cmu(nombre) is not None
    assert proyecto.startswith("Minigranja Solar")


def test_cada_pdf_real_da_su_propio_cmu():
    assert [svc.extraer_cmu(n) for n in ADJUNTOS_REALES_DRIVE] == [
        "CMU1135", "CMU1140", "CMU1147", "CMU1148",
    ]


# ── Qué NO sale del nombre: el tercero ────────────────────────────────────────

@pytest.mark.parametrize("nombre", ADJUNTOS_REALES_DRIVE)
def test_el_tercero_no_esta_en_el_nombre_del_archivo(nombre):
    """La convención real es `CMU####-Mandato-Costos-{Proyecto}.pdf` -- tres
    partes, sin inversionista.

    Consecuencia para la integración: la identidad de Finanzas es
    (proyecto, tercero, periodo, tipo), pero el adjunto solo aporta proyecto y
    tipo. El tercero es el P.A. y vive en el CUERPO del correo
    ("17844 - P.A SOL DE LA SIERRA"). El adaptador tiene que sacarlo de ahí; si
    se confía en el nombre del archivo, toda la identidad colapsa a tercero=''.
    """
    _, tercero = svc.parsear_proyecto_tercero(nombre, svc.tipo_de_nombre(nombre))
    assert tercero == ""


# ── Conviven DOS convenciones de nombre ───────────────────────────────────────

# Cuando el inversionista es una empresa con nombre propio, va en el archivo.
# Estos vienen de tests/test_mandatos.py, que los trae desde Fase A.
NOMBRES_CON_INVERSIONISTA = [
    "CMU0988-Mandato-Costos-Minigranja Solar Uruaco-SUNO ACTIVOS SOSTENIBLES S.A.S..pdf",
    "CMU1017-Mandato-Costos-Minigranja Solar La Cacica-Solenium S.A.S.pdf",
    "CMU0001-Mandato-Costos-PSF - Yurbaqua-Enexa S.A.S.pdf",
]


@pytest.mark.parametrize("nombre", NOMBRES_CON_INVERSIONISTA)
def test_zip_de_fase_a_si_parsea_los_nombres_de_cuatro_partes(nombre):
    """Con inversionista en el nombre, ZIP_NOMBRE_RE funciona. No está roto."""
    assert parsear_nombre_zip(nombre) is not None


@pytest.mark.parametrize("nombre", ADJUNTOS_REALES_DRIVE)
def test_zip_de_fase_a_no_parsea_los_nombres_de_tres_partes(nombre):
    """LIMITACIÓN REAL de `ZIP_NOMBRE_RE`, fijada para que no se pierda.

    El regex exige `-{Inversionista}` antes del `.pdf`. Cuando el mandante es un
    P.A. de fiduciaria (carpeta "Mandato Costos Sol de la Sierra") el archivo
    solo trae `CMU####-Mandato-Costos-{Proyecto}.pdf` y no matchea.
    `POST /mandatos/upload-zip` hace `if not parsed: continue`, así que esos
    archivos se saltan en silencio -- no todos los de un ZIP, solo los de P.A.

    El arreglo no es corregir el regex sino hacer OPCIONAL la parte del
    inversionista, para que acepte las dos formas. Cuando se haga, este test
    hay que invertirlo y el tercero pasa a salir del cuerpo del correo.
    """
    assert parsear_nombre_zip(nombre) is None


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
