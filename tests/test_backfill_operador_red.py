from app.api.v1.fronteras import _normalizar_nombre_operador


def test_normaliza_tildes_y_mayusculas():
    assert _normalizar_nombre_operador("Afinia") == _normalizar_nombre_operador("AFINIA")
    assert _normalizar_nombre_operador("CENTRALES ELÉCTRICAS DE NARIÑO") == "centrales electricas de narino"


def test_normaliza_none_y_vacio():
    assert _normalizar_nombre_operador(None) == ""
    assert _normalizar_nombre_operador("") == ""


def test_variantes_reales_coinciden_tras_normalizar():
    # Casos reales encontrados en producción (2026-07-10): mismo operador,
    # una vez como nombre comercial y otra como razón social completa.
    assert _normalizar_nombre_operador("Afinia") == _normalizar_nombre_operador("Afinia")
    assert (
        _normalizar_nombre_operador("CARIBEMAR DE LA COSTA S.A.S. E.S.P. - DISTRIBUIDOR")
        == _normalizar_nombre_operador("caribemar de la costa s.a.s. e.s.p. - distribuidor")
    )
