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
    assert TIPOS_ENRIQUECIBLES == {"grip", "arrpas", "tgrl", "cxcsb"}
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["grip"] == "PLANTA"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["arrpas"] == "SUBMERCADO"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["cxcsb"] == "SUBMERCADO"
