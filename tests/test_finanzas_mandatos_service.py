from datetime import date
from app.services.finanzas_mandatos_service import (
    tipo_de_nombre, extraer_cmu, extraer_periodo_de_asunto,
    parsear_proyecto_tercero, estado_por_direccion, detectar_comentario,
)

def test_tipo_de_nombre():
    assert tipo_de_nombre("CMU0521-Mandato-Costos-Baraya-SOLENIUM.pdf") == "costo"
    assert tipo_de_nombre("CMU 0183 - Mandato-El Llano-Ayura.pdf") == "ingreso"

def test_extraer_cmu():
    assert extraer_cmu("CMU0521-Mandato-Costos-x.pdf") == "CMU0521"
    assert extraer_cmu("CMU 0183 - Mandato-x.pdf") == "CMU0183"
    assert extraer_cmu("Ajuste Mandato sin codigo.pdf") is None

def test_periodo_de_asunto_con_mes():
    assert extraer_periodo_de_asunto("Re: Revision mandatos de ingresos - Junio",
                                     date(2026, 8, 1)) == date(2026, 6, 1)

def test_periodo_de_asunto_con_anio_explicito():
    assert extraer_periodo_de_asunto("Revision Mandatos de Ingresos Febrero - 2026",
                                     date(2026, 3, 1)) == date(2026, 2, 1)

def test_periodo_borde_diciembre():
    assert extraer_periodo_de_asunto("Re: Revision Mandatos - Diciembre",
                                     date(2027, 1, 5)) == date(2026, 12, 1)

def test_estado_por_direccion():
    rev = "vlondono@jbp.com.co"
    assert estado_por_direccion(f"Vanessa <{rev}>", rev) == "firmado"
    assert estado_por_direccion("Adhara <adhara@unergy.io>", rev) == "sin_firma"

def test_detectar_comentario():
    cuerpo = "Buen dia, el CMU0521 tiene una diferencia en el valor, favor corregir."
    assert detectar_comentario(cuerpo, "CMU0521") is not None
    assert detectar_comentario("Adjunto firmados, gracias", "CMU0521") is None

def test_parsear_proyecto_tercero_costo():
    proj, terc = parsear_proyecto_tercero(
        "CMU0521-Mandato-Costos-Minigranja Solar Baraya-SOLENIUM SAS.pdf", "costo")
    assert proj == "Minigranja Solar Baraya"
    assert terc == "SOLENIUM SAS"


def test_parsear_quita_sufijos_gmail():
    # Los sufijos (1)/(2) que agrega Gmail no deben ensuciar la identidad
    proj, terc = parsear_proyecto_tercero(
        "CMU0521-Mandato-Costos-Minigranja Solar Baraya-SOLENIUM SAS (1).pdf", "costo")
    assert proj == "Minigranja Solar Baraya"
    assert terc == "SOLENIUM SAS"
    proj2, _ = parsear_proyecto_tercero("CMU0184 - Mandato-El Llano Sas Bic (1) (1).pdf", "ingreso")
    assert "(1)" not in proj2
