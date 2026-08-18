"""Tests del parser de correos de mandatos -- funciones puras, sin red ni BD."""
from app.services.mandatos.email_parser import html_a_texto
from tests.fixtures_mandatos_correos import REVISORIA_HTML


def test_html_a_texto_desescapa_entidades():
    texto = html_a_texto("<p>informaci&oacute;n&nbsp;compartida</p>")
    assert texto == "información compartida"


def test_html_a_texto_separa_bloques_en_lineas():
    texto = html_a_texto("<p>uno</p><p>dos</p>")
    assert texto.split("\n") == ["uno", "dos"]


def test_html_a_texto_ignora_script_y_style():
    texto = html_a_texto("<p>visible</p><style>.x{color:red}</style><script>var a=1</script>")
    assert texto == "visible"


def test_html_a_texto_conserva_los_cmu_de_cada_linea():
    texto = html_a_texto(REVISORIA_HTML)
    lineas_con_cmu = [l for l in texto.split("\n") if "CMU" in l]
    assert len(lineas_con_cmu) == 3
    assert "CMU1266,CMU1269,CMU1270 y CMU1271" in lineas_con_cmu[1]


def test_html_a_texto_vacio():
    assert html_a_texto("") == ""
    assert html_a_texto(None) == ""
