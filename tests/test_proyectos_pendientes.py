from app.services import proyectos_pendientes as pp


def _candidato_quoia(estado_sugerido="en_operacion", fase="energizado", multidia=False):
    return pp._Candidato(
        fuentes={"quoia"},
        nombre_raw="GD Garza",
        core="gd garza",
        estado_sugerido=estado_sugerido,
        fase_construccion=fase,
        generacion_multidia=multidia,
    )


def test_reforzar_solo_quoia_descarta_sin_generacion_sostenida():
    # Caso real 2026-07-10: Garza/La Perdiz/Taurus VIII-X -- un solo día de
    # generación (aislado, prueba/calibración) no basta sin corroboración.
    c = _candidato_quoia(multidia=False)
    pp._reforzar_solo_quoia([c])
    assert c.estado_sugerido is None
    assert c.fase_construccion is None


def test_reforzar_solo_quoia_mantiene_con_generacion_sostenida():
    c = _candidato_quoia(multidia=True)
    pp._reforzar_solo_quoia([c])
    assert c.estado_sugerido == "en_operacion"
    assert c.fase_construccion == "energizado"


def test_reforzar_solo_quoia_no_afecta_si_hay_otra_fuente():
    # Con corroboración de Sun Factory/Solenium, el refuerzo no aplica --
    # queda igual que antes (fuera de alcance de este cambio).
    c = _candidato_quoia(multidia=False)
    c.fuentes = {"quoia", "sunfactory"}
    pp._reforzar_solo_quoia([c])
    assert c.estado_sugerido == "en_operacion"
    assert c.fase_construccion == "energizado"


def test_reforzar_solo_quoia_no_afecta_candidatos_sin_sugerencia():
    c = _candidato_quoia(estado_sugerido=None, fase=None, multidia=False)
    pp._reforzar_solo_quoia([c])
    assert c.estado_sugerido is None
    assert c.fase_construccion is None


def test_fusionar_por_core_propaga_generacion_multidia():
    quoia = pp._Candidato(
        fuentes={"quoia"}, nombre_raw="GD Garza", core="gd garza",
        estado_sugerido="en_operacion", fase_construccion="energizado",
        generacion_multidia=True,
    )
    sunfactory = pp._Candidato(
        fuentes={"sunfactory"}, nombre_raw="GD Garza", core="gd garza",
    )
    fusionados = pp._fusionar_por_core([sunfactory, quoia])
    assert len(fusionados) == 1
    assert fusionados[0].generacion_multidia is True
    assert fusionados[0].fuentes == {"quoia", "sunfactory"}
