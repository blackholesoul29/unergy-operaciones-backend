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
