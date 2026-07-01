"""Tests de la estructura canónica del reporte de fallas (funciones puras)."""
from app.services.fallas.estructura import (
    ESTRUCTURA_FALLAS, CATEGORIA_CODIGOS, INVERSOR_TIPO_FALLA_CODIGOS,
    get_categoria, get_opcion, tipo_codigo, etiqueta_subtipo,
    validar_clasificacion, es_subtipo_pendiente, requiere_detalle,
)


def test_cuatro_categorias_canonicas():
    assert CATEGORIA_CODIGOS == {"red", "frontera", "inversores", "eventos_adversos"}


def test_red_tiene_opciones_de_spec():
    red = get_categoria("red")
    codigos = {o["codigo"] for o in red["opciones"]}
    assert codigos == {
        "baja_tension", "alta_tension", "variacion_frecuencia", "mantenimiento_red",
        "acometida_mt", "transformador", "desconexion_sin_identificar",
    }


def test_frontera_equipos_y_flags():
    f = get_categoria("frontera")
    equipos = {o["codigo"] for o in f["opciones"]}
    assert equipos == {"medidor_principal", "medidor_respaldo", "ct", "pt", "caja_pruebas", "modem_comunicaciones"}
    flags = {fl["codigo"] for fl in f["flags"]}
    assert flags == {"afecta_medicion", "perdida_comunicacion"}


def test_inversores_tipos_falla():
    assert INVERSOR_TIPO_FALLA_CODIGOS == {
        "baja_tension_ac", "baja_tension_dc", "baja_resistencia_aislamiento",
        "problemas_ventilacion", "falla_dispositivo", "problema_cadena_fotovoltaica",
        "sobre_temperatura", "arco_ac", "arco_dc", "perdida_comunicacion",
    }


def test_inversores_tipos_legacy_conservan_etiqueta():
    # Los tipos retirados ya no son válidos para reportar, pero su etiqueta
    # sigue resolviéndose para no degradar fallas históricas.
    assert "no_generacion" not in INVERSOR_TIPO_FALLA_CODIGOS
    assert etiqueta_subtipo("inversores", "no_generacion") == "No generación"


def test_eventos_adversos():
    ev = get_categoria("eventos_adversos")
    codigos = {o["codigo"] for o in ev["opciones"]}
    assert codigos == {"incendio", "inundacion", "huracan", "otro"}


def test_tipo_codigo_es_calificado():
    assert tipo_codigo("red", "baja_tension") == "red.baja_tension"


def test_etiqueta_subtipo():
    assert etiqueta_subtipo("frontera", "medidor_principal") == "Medidor principal"
    assert etiqueta_subtipo("inversores", "no_generacion") == "No generación"
    assert etiqueta_subtipo("red", "no_existe") is None


# ── validar_clasificacion ────────────────────────────────────────────────────
def test_validar_categoria_desconocida():
    ok, err = validar_clasificacion("inexistente", "x")
    assert not ok and "desconocida" in err


def test_validar_red_ok():
    assert validar_clasificacion("red", "baja_tension") == (True, None)


def test_validar_red_subtipo_invalido():
    ok, err = validar_clasificacion("red", "no_existe")
    assert not ok and "inválida" in err


def test_validar_red_sin_subtipo():
    ok, err = validar_clasificacion("red", None)
    assert not ok


def test_validar_frontera_equipo_ok():
    assert validar_clasificacion("frontera", "ct") == (True, None)


def test_validar_inversores_requiere_tipos():
    ok, err = validar_clasificacion("inversores", None, inversores_tipos=[])
    assert not ok and "tipo de falla" in err


def test_validar_inversores_tipos_ok():
    assert validar_clasificacion("inversores", None, inversores_tipos=["baja_tension_ac", "perdida_comunicacion"]) == (True, None)


def test_validar_inversores_tipos_invalidos():
    ok, err = validar_clasificacion("inversores", None, inversores_tipos=["xyz"])
    assert not ok and "inválidos" in err


# ── pendiente_reclasificar / requiere_detalle ────────────────────────────────
def test_desconexion_sin_identificar_es_pendiente():
    assert es_subtipo_pendiente("red", "desconexion_sin_identificar") is True
    assert es_subtipo_pendiente("red", "baja_tension") is False


def test_mantenimiento_red_requiere_detalle():
    assert requiere_detalle("red", "mantenimiento_red") is True
    assert requiere_detalle("red", "baja_tension") is False


def test_otro_evento_requiere_detalle():
    assert requiere_detalle("eventos_adversos", "otro") is True
    assert requiere_detalle("eventos_adversos", "incendio") is False
