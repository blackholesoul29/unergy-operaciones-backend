"""Tests de las funciones puras del servicio de mandatos."""
from datetime import date
from types import SimpleNamespace

from app.services.mandatos_service import (
    extraer_cmus, extraer_cmu_de_nombre, mes_a_periodo,
    transicion_valida, mandato_to_dict, calcular_resumen,
)


# ── extraer_cmus ──────────────────────────────────────────────────────────────

def test_extraer_cmus_del_cuerpo():
    texto = ("CMU0988 / CMU0993 / CMU0996 / CMU1003 / CMU1005 / "
             "CMU1016 / CMU1017 / CMU1018 / CMU1019")
    assert extraer_cmus(texto) == [
        "CMU0988", "CMU0993", "CMU0996", "CMU1003", "CMU1005",
        "CMU1016", "CMU1017", "CMU1018", "CMU1019",
    ]

def test_extraer_cmus_sin_duplicados_y_orden_de_aparicion():
    assert extraer_cmus("CMU0975 texto CMU0975 luego CMU0001") == ["CMU0975", "CMU0001"]

def test_extraer_cmus_vacio():
    assert extraer_cmus("sin codigos aqui") == []


# ── extraer_cmu_de_nombre ─────────────────────────────────────────────────────

def test_extraer_cmu_de_nombre_archivo():
    assert extraer_cmu_de_nombre("CMU0975_firmado.pdf") == "CMU0975"

def test_extraer_cmu_de_nombre_sin_match():
    assert extraer_cmu_de_nombre("documento_final.pdf") is None


# ── mes_a_periodo ─────────────────────────────────────────────────────────────

def test_mes_a_periodo_mayo():
    assert mes_a_periodo("Mayo", 2025) == date(2025, 5, 1)

def test_mes_a_periodo_con_tildes_y_mayusculas():
    assert mes_a_periodo("DICIEMBRE", 2025) == date(2025, 12, 1)

def test_mes_a_periodo_invalido():
    assert mes_a_periodo("NoEsUnMes", 2025) is None


# ── transicion_valida ─────────────────────────────────────────────────────────

def test_transicion_valida_envio_a_correcciones():
    assert transicion_valida("enviado_revisoria", "con_correcciones") is True

def test_transicion_valida_firma_directa_sin_correcciones():
    assert transicion_valida("enviado_revisoria", "firmado") is True

def test_transicion_invalida_salto_atras():
    assert transicion_valida("firmado", "pendiente_envio") is False


# ── mandato_to_dict ───────────────────────────────────────────────────────────

def _row(**kw):
    base = dict(
        id=1, cmu="CMU0988", periodo=date(2025, 5, 1), proyecto="Minigranja Solar Baraya",
        tercero="Sun-Capital", inversionista_id=None, estado="con_correcciones",
        observacion="novedad en la contabilización del arriendo",
        fecha_envio_revisoria=date(2025, 5, 10), fecha_firmado=None,
        fecha_envio_inversionista=None, pdf_firmado_ruta=None, pdf_firmado_nombre=None,
        correo_ref_revisoria=None, correo_ref_envio=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)

def test_mandato_to_dict_campos_basicos():
    out = mandato_to_dict(_row())
    assert out["cmu"] == "CMU0988"
    assert out["periodo"] == "2025-05"
    assert out["estado"] == "con_correcciones"
    assert out["tiene_pdf"] is False

def test_mandato_to_dict_pdf_disponible():
    out = mandato_to_dict(_row(pdf_firmado_ruta="uploads/mandatos/CMU0975.pdf"))
    assert out["tiene_pdf"] is True

def test_mandato_to_dict_fecha_inversionista_iso():
    out = mandato_to_dict(_row(fecha_envio_inversionista=date(2025, 5, 15)))
    assert out["fecha_envio_inversionista"] == "2025-05-15"


# ── calcular_resumen ──────────────────────────────────────────────────────────

def test_calcular_resumen_conteos():
    filas = [
        _row(estado="con_correcciones"),
        _row(estado="con_correcciones"),
        _row(estado="firmado"),
        _row(estado="enviado_inversionista"),
        _row(estado="pendiente_envio"),
        _row(estado="enviado_revisoria"),
    ]
    r = calcular_resumen(filas)
    assert r["total"] == 6
    assert r["correcciones"] == 2
    assert r["firmados"] == 1
    assert r["enviados_inversionista"] == 1
    assert r["pendientes"] == 2   # pendiente_envio + enviado_revisoria


# ── parsear_nombre_zip ────────────────────────────────────────────────────────
from app.services.mandatos_service import parsear_nombre_zip, match_inversionista

def test_parsear_nombre_zip_suno_doble_punto():
    r = parsear_nombre_zip("CMU0988-Mandato-Costos-Minigranja Solar Uruaco-SUNO ACTIVOS SOSTENIBLES S.A.S..pdf")
    assert r["cmu"] == "CMU0988"
    assert r["proyecto"] == "Minigranja Solar Uruaco"
    assert r["inversionista"].startswith("SUNO ACTIVOS SOSTENIBLES S.A.S")

def test_parsear_nombre_zip_solenium():
    r = parsear_nombre_zip("CMU1017-Mandato-Costos-Minigranja Solar La Cacica-Solenium S.A.S.pdf")
    assert r["cmu"] == "CMU1017"
    assert r["proyecto"] == "Minigranja Solar La Cacica"
    assert r["inversionista"].startswith("Solenium")

def test_parsear_nombre_zip_proyecto_con_guion():
    r = parsear_nombre_zip("CMU0001-Mandato-Costos-PSF - Yurbaqua-Enexa S.A.S.pdf")
    assert r["cmu"] == "CMU0001"
    assert r["proyecto"] == "PSF - Yurbaqua"
    assert r["inversionista"].startswith("Enexa")

def test_parsear_nombre_zip_no_valido():
    assert parsear_nombre_zip("documento_cualquiera.pdf") is None

def test_parsear_nombre_zip_sin_inversionista_pa_fiduciaria():
    """Convención de TRES partes: cuando el mandante es un P.A. de fiduciaria,
    el archivo no trae inversionista (carpeta 'Mandato Costos Sol de la Sierra',
    captura 2026-08-18). El inversionista queda vacío, no se inventa."""
    r = parsear_nombre_zip("CMU1140-Mandato-Costos-Minigranja Solar Merengue.pdf")
    assert r == {"cmu": "CMU1140", "proyecto": "Minigranja Solar Merengue",
                 "inversionista": "",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_sin_inversionista_proyecto_con_guion():
    """El caso que obliga al lookaround: sin la señal del espaciado, esto se
    partiría en ('PSF', 'Yurbaqua') e inventaría un inversionista."""
    r = parsear_nombre_zip("CMU0002-Mandato-Costos-PSF - Yurbaqua.pdf")
    assert r == {"cmu": "CMU0002", "proyecto": "PSF - Yurbaqua",
                 "inversionista": "",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_proyecto_con_numero_al_final():
    """'Valencia Oriente 1' no debe confundirse con un inversionista."""
    r = parsear_nombre_zip("CMU0003-Mandato-Costos-Minigranja Solar Valencia Oriente 1.pdf")
    assert r == {"cmu": "CMU0003", "proyecto": "Minigranja Solar Valencia Oriente 1",
                 "inversionista": "",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_convencion_ingresos_sin_costos():
    """Autoconsumo/ingresos: `CMU####-Mandato-{Proyecto}.pdf`, sin 'Costos'."""
    r = parsear_nombre_zip("CMU1182-Mandato-Iml Empaques Colombia Sas.pdf")
    assert r == {"cmu": "CMU1182", "proyecto": "Iml Empaques Colombia Sas",
                 "inversionista": "",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_ingresos_con_inversionista():
    r = parsear_nombre_zip(
        "CMU1228-Mandato-GD Delta 1-GRANJAS SOLARES DELTA S.A.S. E.S.P.pdf")
    assert r == {"cmu": "CMU1228", "proyecto": "GD Delta 1",
                 "inversionista": "GRANJAS SOLARES DELTA S.A.S. E.S.P",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_proyecto_terminado_en_punto():
    r = parsear_nombre_zip("CMU0907-Mandato-Arcillas San Simon S.A.S..pdf")
    assert r == {"cmu": "CMU0907", "proyecto": "Arcillas San Simon S.A.S.",
                 "inversionista": "",
                 "pa_codigo": "", "pa_nombre": ""}


def test_parsear_nombre_zip_limpia_el_sufijo_de_gmail():
    """Gmail agrega ' (1)' a los adjuntos repetidos. Sin limpiarlo se cuela en
    el inversionista y parte la identidad en dos filas distintas."""
    r = parsear_nombre_zip(
        "CMU1255-Mandato-Costos-Minigranja Solar Esmeralda-"
        "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA (1).pdf")
    assert r["inversionista"] == (
        "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA")


def test_parsear_nombre_zip_ignora_un_pdf_que_no_es_mandato():
    """De la primera tanda: una liquidación adjunta en el mismo hilo."""
    assert parsear_nombre_zip("Liquidacion_CoxEnergy_Jul2026.pdf") is None

# ── match_inversionista ───────────────────────────────────────────────────────
MAESTRA_T = [{"id": 13, "nombre": "Suno"}, {"id": 2, "nombre": "Solenium"}, {"id": 7, "nombre": "Credicorp"}]

def test_match_exacto():
    inv_id, sug, score = match_inversionista("Suno", MAESTRA_T)
    assert inv_id == 13 and sug is None and score == 1.0

def test_match_substring_autolink():
    inv_id, sug, score = match_inversionista("SUNO ACTIVOS SOSTENIBLES S.A.S.", MAESTRA_T)
    assert inv_id == 13 and sug is None

def test_match_fuzzy_sugerencia():
    inv_id, sug, score = match_inversionista("Solenum S.A.S", MAESTRA_T)
    assert inv_id is None
    assert sug is not None and sug["sugerido_id"] == 2 and score >= 0.6

def test_match_sin_candidato():
    inv_id, sug, score = match_inversionista("Petrolera Nacional del Sur", MAESTRA_T)
    assert inv_id is None and sug is None

# ── mandato_to_dict: archivo_zip_nombre ──────────────────────────────────────
def test_mandato_to_dict_pdf_zip():
    out = mandato_to_dict(_row(archivo_zip_nombre="CMU0988-Mandato-Costos-X-Y.pdf"))
    assert out["archivo_zip_nombre"] == "CMU0988-Mandato-Costos-X-Y.pdf"
    assert out["tiene_pdf_zip"] is True

def test_mandato_to_dict_sin_pdf_zip():
    out = mandato_to_dict(_row())
    assert out["tiene_pdf_zip"] is False


# ── cuarta convención: el P.A. al final del nombre ────────────────────────────
# Lote real de Sol de la Sierra (2026-08-20). Antes, el proyecto se tragaba todo
# el resto del nombre y el inversionista salía vacío: una identidad falsa por
# cada mandato.

def test_nombre_con_pa_al_final_separa_las_tres_partes():
    from app.services.mandatos_service import parsear_nombre_zip
    p = parsear_nombre_zip(
        "CMU1140-Mandato-Costos-Minigranja Solar Merengue-PATRIMONIOS AUTONOMOS "
        "FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA.pdf")
    assert p["cmu"] == "CMU1140"
    assert p["proyecto"] == "Minigranja Solar Merengue"
    assert p["inversionista"].startswith("PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA")
    assert (p["pa_codigo"], p["pa_nombre"]) == ("17844", "SOL DE LA SIERRA")


def test_un_proyecto_con_guion_espaciado_no_se_confunde_con_un_pa():
    """El recorte se ancla al CÓDIGO numérico, no al guion espaciado: un
    proyecto sí puede llevar ' - ' en su nombre."""
    from app.services.mandatos_service import parsear_nombre_zip
    p = parsear_nombre_zip("CMU0500-Mandato-Costos-PSF - Yurbaqua.pdf")
    assert p["proyecto"] == "PSF - Yurbaqua"
    assert p["pa_codigo"] == ""


def test_nombre_sin_pa_deja_los_campos_vacios():
    from app.services.mandatos_service import parsear_nombre_zip
    p = parsear_nombre_zip("CMU1170-Mandato-Edificio Torre Almagran Propiedad Horizontal.pdf")
    assert (p["pa_codigo"], p["pa_nombre"], p["inversionista"]) == ("", "", "")
