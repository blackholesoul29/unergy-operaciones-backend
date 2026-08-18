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


def test_html_a_texto_separa_celdas_de_tabla_con_espacio():
    texto = html_a_texto(REVISORIA_HTML)
    assert "Certificado Contabilidad" in texto
    assert "5,703,802 5,475,170.65" in texto


def test_html_a_texto_recupera_texto_tras_script_sin_cerrar():
    texto = html_a_texto("<p>antes</p><script>var a = 1;<p>CMU1266 dato importante</p>")
    assert "CMU1266" in texto


def test_html_a_texto_no_revienta_con_etiquetas_sin_cerrar():
    texto = html_a_texto("<div><p>CMU1000 texto")
    assert "CMU1000" in texto


def test_html_a_texto_limite_conocido_script_sin_cerrar_con_token_malformado():
    """Fija un límite ACEPTADO, no un comportamiento deseado.

    Si un <script> sin cerrar contiene además un token con forma de etiqueta
    sin terminar (`<div){...}` sin ">"), el tokenizador se traga el resto y ese
    contenido se pierde. Requiere dos rarezas simultáneas y arreglarlo exigiría
    reimplementar recuperación de tokens malformados (ver comentario en
    handle_starttag). Este test existe para que un refactor futuro que cambie
    esto -- para bien o para mal -- no pase inadvertido.
    """
    texto = html_a_texto("<p>antes</p><script>if(a<div){secreto=3}<p>CMU3333</p>")
    assert texto == "antes"
