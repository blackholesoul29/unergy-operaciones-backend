from datetime import date, timedelta

from app.services import proyectos_pendientes as pp


class _FakeSoleniumClient:
    enabled = True

    def __init__(self, proyectos, generacion_por_id):
        self._proyectos = proyectos
        self._generacion_por_id = generacion_por_id

    def get_projects(self):
        return self._proyectos

    def get_generation(self, project_id, date_from, date_to):
        return self._generacion_por_id.get(project_id, {})


def _proyecto_solenium(id=1, name="GD Ejemplo"):
    return {
        "id": id, "name": name, "installed_capacity": 500,
        "is_minifarm": False, "is_self_consumption": False,
        "lat": None, "lon": None,
    }


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


def test_candidatos_solenium_no_sugiere_operando_sin_generacion_real(monkeypatch):
    # Solenium marcaba TODO su listado como "en_operacion" sin verificar nada
    # -- aparecer en el sistema de monitoreo no prueba que ya opere.
    monkeypatch.setattr(pp, "_generacion_solenium_cache", None)
    client = _FakeSoleniumClient([_proyecto_solenium(1)], {1: {}})
    monkeypatch.setattr(pp, "SoleniumClient", lambda: client)

    out = pp._candidatos_solenium()
    assert len(out) == 1
    assert out[0].estado_sugerido is None
    assert out[0].fase_construccion is None


def test_candidatos_solenium_sugiere_operando_con_generacion_sostenida(monkeypatch):
    monkeypatch.setattr(pp, "_generacion_solenium_cache", None)
    hoy = date.today()
    dias_ventana = [(hoy - timedelta(days=i)).isoformat() for i in range(1, pp._DIAS_GENERACION_SOSTENIDA + 1)]
    gen_kwh_map = {f"{d}T12:00:00": 10.0 for d in dias_ventana}
    client = _FakeSoleniumClient([_proyecto_solenium(2)], {2: {"generation_kwh": gen_kwh_map}})
    monkeypatch.setattr(pp, "SoleniumClient", lambda: client)

    out = pp._candidatos_solenium()
    assert len(out) == 1
    assert out[0].estado_sugerido == "en_operacion"
    assert out[0].fase_construccion == "energizado"


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
