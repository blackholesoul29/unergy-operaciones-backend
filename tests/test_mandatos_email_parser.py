"""Tests del parser de correos de mandatos -- funciones puras, sin red ni BD."""
from app.services.mandatos.email_parser import (
    CLASIF_DESCONOCIDO, CLASIF_MOLDE_SIMPLE, CLASIF_SEGUIMIENTO,
    clasificar_correo, cmu_al_inicio_de_nombre, extraer_observaciones,
    html_a_texto, solo_pdfs,
)
from tests.fixtures_mandatos_correos import (
    ENVIO_INVERSIONISTA_ADJUNTOS, LIQUIDACION_PRELIMINAR_ADJUNTOS,
    REVISORIA_HTML, REVISORIA_MIXTO, REVISORIA_OBSERVACIONES,
    REVISORIA_SEGUIMIENTO,
)


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


# ── clasificar_correo ─────────────────────────────────────────────────────────

def test_clasificar_observaciones_nuevas_es_molde_simple():
    assert clasificar_correo("Mandatos de costos julio", REVISORIA_OBSERVACIONES) == CLASIF_MOLDE_SIMPLE


def test_clasificar_correo_mixto_es_molde_simple():
    assert clasificar_correo("Certificados Sol de la Sierra", REVISORIA_MIXTO) == CLASIF_MOLDE_SIMPLE


def test_clasificar_seguimiento_no_se_interpreta():
    """El correo donde CMU1255 quedó resuelto. Si esto se rompe, el sistema
    empieza a marcar mandatos resueltos como con_correcciones."""
    assert clasificar_correo("Mandatos de costos julio", REVISORIA_SEGUIMIENTO) == CLASIF_SEGUIMIENTO


def test_clasificar_asunto_re_es_seguimiento():
    assert clasificar_correo("RE: Certificados", "encuentro las siguientes observaciones: CMU1000 mal") == CLASIF_SEGUIMIENTO


def test_seguimiento_gana_sobre_molde_simple():
    """Ante señales de ambos, gana seguimiento -- falla hacia el lado seguro."""
    cuerpo = "Agradezco su respuesta. Encuentro las siguientes observaciones: CMU1000 mal"
    assert clasificar_correo("Certificados", cuerpo) == CLASIF_SEGUIMIENTO


def test_clasificar_correo_sin_senales_es_desconocido():
    assert clasificar_correo("Hola", "Buenas tardes, quedo atenta.") == CLASIF_DESCONOCIDO


# ── extraer_observaciones ─────────────────────────────────────────────────────

def test_extraer_observaciones_correo_real():
    obs = extraer_observaciones(REVISORIA_OBSERVACIONES)
    assert [o["cmu"] for o in obs] == [
        "CMU1255", "CMU1266", "CMU1269", "CMU1270", "CMU1271", "CMU1284",
    ]


def test_varios_cmu_en_una_linea_comparten_observacion():
    obs = {o["cmu"]: o["observacion"] for o in extraer_observaciones(REVISORIA_OBSERVACIONES)}
    esperado = "no se evidencia contabilización del internet, el IVA y el arriendo"
    assert obs["CMU1266"] == esperado
    assert obs["CMU1271"] == esperado


def test_observacion_arranca_despues_del_ultimo_cmu():
    obs = {o["cmu"]: o["observacion"] for o in extraer_observaciones(REVISORIA_OBSERVACIONES)}
    assert obs["CMU1255"].startswith("el valor a pagar no coincide")
    assert obs["CMU1284"] == "no se evidencia contabilización"


def test_extraer_observaciones_correo_mixto():
    obs = extraer_observaciones(REVISORIA_MIXTO)
    assert [o["cmu"] for o in obs] == ["CMU1052", "CMU1122"]
    assert obs[0]["observacion"] == "No se evidencia contabilización del mantenimiento y el IVA de este"


def test_extraer_observaciones_corta_en_la_firma():
    cuerpo = "CMU1000 tiene novedad\nCordialmente\nCMU9999 esto es parte de la firma"
    assert [o["cmu"] for o in extraer_observaciones(cuerpo)] == ["CMU1000"]


def test_extraer_observaciones_sin_cmu():
    assert extraer_observaciones("Buenas tardes, quedo atenta.") == []


# ── adjuntos ──────────────────────────────────────────────────────────────────

def test_cmu_al_inicio_de_nombre_convencion_de_jessica():
    assert cmu_al_inicio_de_nombre("CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf") == "CMU1135"


def test_cmu_al_inicio_ignora_cmu_en_medio_del_nombre():
    """Ancla al inicio: un CMU suelto en medio del nombre no cuenta para Fuente 3."""
    assert cmu_al_inicio_de_nombre("REGISTRO MANDATOS CMU1135.xlsx") is None


def test_cmu_al_inicio_sin_match():
    assert cmu_al_inicio_de_nombre("REGISTRO MANDATOS.xlsx") is None
    assert cmu_al_inicio_de_nombre("") is None
    assert cmu_al_inicio_de_nombre(None) is None


def test_solo_pdfs_descarta_el_excel():
    assert solo_pdfs(ENVIO_INVERSIONISTA_ADJUNTOS) == [
        "CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1141-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1139-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1142-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    ]


def test_liquidacion_preliminar_no_aporta_cmu():
    """Caso negativo: correo de Jessica a inversionistas que menciona
    'certificados de mandato' pero no trae adjuntos de mandato."""
    pdfs = solo_pdfs(LIQUIDACION_PRELIMINAR_ADJUNTOS)
    assert [cmu_al_inicio_de_nombre(n) for n in pdfs] == []


# ── extraer_observaciones no debe leer el historial citado ────────────────────

def test_extraer_observaciones_no_lee_cita_estilo_gmail():
    """Repro del hallazgo: un CMU resuelto citado del hilo anterior no debe
    colarse como observación nueva."""
    cuerpo = (
        "Encuentro las siguientes observaciones:\n"
        "CMU1266 no se evidencia contabilizacion del arriendo\n"
        "\n"
        "El vie, 10 ago 2026 a las 14:25, Vanessa <...> escribio:\n"
        "> Certificado CMU1284 ya se encuentra resuelto"
    )
    cmus = [o["cmu"] for o in extraer_observaciones(cuerpo)]
    assert "CMU1266" in cmus
    assert "CMU1284" not in cmus


def test_extraer_observaciones_no_lee_lineas_con_prefijo_mayor_que():
    cuerpo = (
        "Encuentro las siguientes observaciones:\n"
        "CMU1000 tiene novedad nueva\n"
        "> CMU9999 esto viene del correo anterior\n"
    )
    assert [o["cmu"] for o in extraer_observaciones(cuerpo)] == ["CMU1000"]


def test_extraer_observaciones_no_lee_tras_separador_outlook():
    cuerpo = (
        "Encuentro las siguientes observaciones:\n"
        "CMU1000 tiene novedad nueva\n"
        "-----Mensaje original-----\n"
        "CMU9999 esto viene del correo anterior\n"
    )
    assert [o["cmu"] for o in extraer_observaciones(cuerpo)] == ["CMU1000"]


def test_extraer_observaciones_sin_cita_no_se_recorta():
    """Guarda de regresión más importante: un correo sin ninguna cita debe
    seguir devolviendo la lista completa de CMU."""
    obs = extraer_observaciones(REVISORIA_OBSERVACIONES)
    assert [o["cmu"] for o in obs] == [
        "CMU1255", "CMU1266", "CMU1269", "CMU1270", "CMU1271", "CMU1284",
    ]
