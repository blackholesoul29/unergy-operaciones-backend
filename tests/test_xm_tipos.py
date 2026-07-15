import pytest
from app.services.xm.tipos import (
    validar_tipo, TipoXMInvalido, ruta_directorio, es_mensual, nombre_archivo,
    TIPOS_ENRIQUECIBLES, COLUMNA_CODIGO_ENRIQUECIMIENTO,
)


def test_validar_tipo_conocido_no_lanza():
    validar_tipo("grip")


def test_validar_tipo_desconocido_lanza():
    with pytest.raises(TipoXMInvalido):
        validar_tipo("no_existe")


def test_ruta_directorio_publica():
    assert ruta_directorio("grip", 2026, 5) == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_ruta_directorio_privada():
    assert ruta_directorio("dspcttos", 2026, 5) == "/INFORMACION_XM/USUARIOSK/UNGG/SIC/COMERCIA/2026-05"


def test_es_mensual_cxcsb_true_y_grip_false():
    assert es_mensual("cxcsb") is True
    assert es_mensual("grip") is False


def test_nombre_archivo_diario():
    assert nombre_archivo("grip", "txf", 2026, 5, 7) == "grip0507.txf"


def test_nombre_archivo_mensual():
    assert nombre_archivo("cxcsb", "TXF", 2026, 5) == "cxcsb05.txf"


def test_nombre_archivo_diario_sin_dia_lanza():
    with pytest.raises(ValueError):
        nombre_archivo("grip", "txf", 2026, 5)


def test_tipos_enriquecibles_y_columna():
    # tgrl NO es enriquecible por SIC (columnas CODIGO/AGENTE, sin código de
    # planta); se filtra por agente. Solo grip/arrpas/cxcsb tienen PLANTA/SUBMERCADO.
    assert TIPOS_ENRIQUECIBLES == {"grip", "arrpas", "cxcsb"}
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["grip"] == "PLANTA"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["arrpas"] == "SUBMERCADO"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["cxcsb"] == "SUBMERCADO"
    assert "tgrl" not in TIPOS_ENRIQUECIBLES
    assert "tgrl" not in COLUMNA_CODIGO_ENRIQUECIMIENTO


def test_tgrl_se_filtra_por_agente():
    from app.services.xm.tipos import TIPOS_FILTRO_AGENTE, TIPOS_FILTRABLES
    assert "tgrl" in TIPOS_FILTRO_AGENTE
    # el checkbox aplica tanto a los enriquecibles por SIC como a tgrl
    assert TIPOS_FILTRABLES == {"grip", "arrpas", "cxcsb", "tgrl"}


def test_tserv_es_publico_y_mensual():
    validar_tipo("tserv")
    assert ruta_directorio("tserv", 2026, 5) == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"
    assert es_mensual("tserv") is True
    assert nombre_archivo("tserv", "txf", 2026, 5) == "tserv05.txf"


def test_afac_es_publico_y_mensual():
    validar_tipo("afac")
    assert ruta_directorio("afac", 2026, 5) == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"
    assert es_mensual("afac") is True
    assert nombre_archivo("afac", "txf", 2026, 5) == "afac05.txf"
