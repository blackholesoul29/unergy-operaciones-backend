"""Tests del emparejador semántico de resoluciones de falla (funciones puras).

Cubre el plan de pruebas:
  - 20 descripciones diversas (typos, jerga, longitudes variadas) -> código correcto
    con confianza >= umbral.
  - Casos límite sin match claro -> se marcan PENDING_REVIEW.
  - Regresión: los códigos crudos del catálogo se auto-emparejan.
"""
import pytest

from app.utils.falla_resolution_matcher import (
    FallaResolutionMatcher,
    DEFAULT_THRESHOLD,
    STATUS_MATCHED,
    STATUS_PENDING,
)

RESOLUTION_CODES = [
    "reinicio_inversor",
    "visita_tecnica",
    "cambio_componente",
    "actualizacion_fw",
    "intervencion_red",
    "resolucion_remota",
    "sin_accion",
    "otro",
]


@pytest.fixture(scope="module")
def matcher():
    return FallaResolutionMatcher(RESOLUTION_CODES)


# (texto de entrada, código esperado) — 20 variaciones diversas.
CASOS_MATCH = [
    # reinicio_inversor
    ("Se reinició el inversor", "reinicio_inversor"),
    ("reinicio de inversor central", "reinicio_inversor"),
    ("hubo que resetear el inversor", "reinicio_inversor"),
    # visita_tecnica
    ("Visita técnica al sitio", "visita_tecnica"),
    ("se hizo una visita de tecnico", "visita_tecnica"),
    ("revisión en sitio del equipo", "visita_tecnica"),
    # cambio_componente
    ("Cambio de componente dañado", "cambio_componente"),
    ("reemplazo de componente quemado", "cambio_componente"),
    ("cambio de tarjeta electronica", "cambio_componente"),
    # actualizacion_fw
    ("Actualización de firmware del inversor", "actualizacion_fw"),
    ("update de firmware", "actualizacion_fw"),
    ("actualizacion de software del equipo", "actualizacion_fw"),
    # intervencion_red
    ("Intervención del operador de red", "intervencion_red"),
    ("falla del operador de red", "intervencion_red"),
    # resolucion_remota
    ("Resolución remota del incidente", "resolucion_remota"),
    ("se solucionó por gestión remota", "resolucion_remota"),
    ("telegestion del equipo", "resolucion_remota"),
    # sin_accion
    ("Sin acción requerida", "sin_accion"),
    ("no aplica ninguna acción", "sin_accion"),
    ("no requiere accion", "sin_accion"),
]


@pytest.mark.parametrize("texto,esperado", CASOS_MATCH)
def test_variaciones_mapean_al_codigo_correcto(matcher, texto, esperado):
    result = matcher.match(texto)
    assert result["code"] == esperado, (
        f"{texto!r} -> {result['code']} (conf {result['confidence']}), "
        f"esperaba {esperado}"
    )
    assert result["confidence"] >= DEFAULT_THRESHOLD
    assert result["status"] == STATUS_MATCHED


def test_al_menos_veinte_casos():
    assert len(CASOS_MATCH) >= 20


@pytest.mark.parametrize("texto", [
    "xyz qwerty asdf",              # ruido sin sentido
    "el clima estuvo soleado hoy",  # totalmente fuera de dominio
    "12345",                        # solo números
    "???",                          # símbolos
])
def test_sin_match_claro_marca_revision(matcher, texto):
    result = matcher.match(texto)
    assert result["status"] == STATUS_PENDING
    assert result["confidence"] < DEFAULT_THRESHOLD
    # el texto original se conserva para la revisión humana
    assert result["description"] == texto


def test_texto_vacio_es_pending_sin_codigo(matcher):
    for vacio in ["", "   ", None]:
        result = matcher.match(vacio)
        assert result["status"] == STATUS_PENDING
        assert result["code"] is None
        assert result["confidence"] == 0


# Regresión (falso POSITIVO): un único término común del catálogo dentro de un texto
# largo de OTRO tema puntuaba 100 por subconjunto (token_set_ratio) y se auto-clasificaba
# MATCHED, saltándose la revisión. Al no tener sinónimos de un solo token común, estas
# descripciones ya no alcanzan el umbral y caen a PENDING_REVIEW.
CASOS_FALSO_POSITIVO = [
    "No fue necesario reinicio, se cambió el panel dañado en sitio",
    "Se coordinó visita con el cliente para reunión comercial",
    "El firmware del router de oficina se actualizó, nada que ver con la planta",
    "Se reemplazó el filtro de agua de la cocina de la oficina",
    "Sin novedad, el operador reportó todo normal en la visita administrativa",
    "Se hizo mantenimiento preventivo general de la planta",
]


@pytest.mark.parametrize("texto", CASOS_FALSO_POSITIVO)
def test_termino_suelto_en_texto_ajeno_va_a_revision(matcher, texto):
    result = matcher.match(texto)
    assert result["status"] == STATUS_PENDING, (
        f"{texto!r} se auto-clasificó como {result['code']} "
        f"(conf {result['confidence']}) en vez de ir a revisión manual"
    )
    assert result["confidence"] < DEFAULT_THRESHOLD


# Regresión (falso NEGATIVO): una descripción legítima on-topic y VERBOSA (una oración
# completa, como las que llegan desde Sheets) que contiene la frase del catálogo debe
# seguir emparejando — el texto libre real casi nunca es de 3 palabras. Si el matcher
# solo acertara en frases terse, la mayoría de las resoluciones caerían a 'otro' y la
# cola de revisión sería inmanejable, anulando el auto-emparejador.
CASOS_MATCH_VERBOSO = [
    ("Se realizó la actualización de firmware del inversor central de la planta solar "
     "porque presentaba fallo de comunicación recurrente", "actualizacion_fw"),
    ("El técnico de mantenimiento realizó una visita técnica al sitio para revisar el "
     "estado de los equipos", "visita_tecnica"),
    ("Fue necesario el cambio de componente dañado, específicamente la tarjeta de "
     "control del inversor", "cambio_componente"),
    ("El equipo se reinició de forma remota mediante gestión remota desde el centro de "
     "monitoreo", "resolucion_remota"),
    ("Se procedió a reiniciar el inversor número 3 que estaba en falla",
     "reinicio_inversor"),
    ("Intervención del operador de red por corte programado en la zona",
     "intervencion_red"),
]


@pytest.mark.parametrize("texto,esperado", CASOS_MATCH_VERBOSO)
def test_descripcion_verbosa_on_topic_sigue_matcheando(matcher, texto, esperado):
    result = matcher.match(texto)
    assert result["code"] == esperado, (
        f"{texto!r} -> {result['code']} (conf {result['confidence']}), "
        f"esperaba {esperado}"
    )
    assert result["status"] == STATUS_MATCHED
    assert result["confidence"] >= DEFAULT_THRESHOLD


def test_palabra_otro_en_texto_ajeno_no_auto_matchea(matcher):
    # El catch-all 'otro' no es un objetivo semántico: un texto que contiene la palabra
    # literal "otro" no debe auto-clasificarse @100 como 'otro' (saltándose la revisión).
    result = matcher.match("otro día volvieron a llamar por la factura pendiente")
    assert result["status"] == STATUS_PENDING, (
        f"'otro' en texto ajeno se auto-clasificó: {result}"
    )
    assert result["code"] != "otro" or result["confidence"] < DEFAULT_THRESHOLD


def test_celda_terse_de_una_palabra_sigue_matcheando(matcher):
    # Aunque se quitaron los sinónimos de un token, una celda que ES solo esa palabra
    # sigue matcheando: token_set_ratio es simétrico ante subconjuntos (la query es
    # subconjunto de la frase de 2 tokens). No se pierde recall en celdas terse.
    for texto, esperado in [("reinicio", "reinicio_inversor"),
                            ("visita", "visita_tecnica"),
                            ("firmware", "actualizacion_fw")]:
        result = matcher.match(texto)
        assert result["status"] == STATUS_MATCHED, f"{texto!r} -> {result}"
        assert result["code"] == esperado


def test_codigos_crudos_del_catalogo_auto_emparejan(matcher):
    """Regresión: cada código canónico debe emparejarse consigo mismo."""
    for code in RESOLUTION_CODES:
        if code == "otro":
            continue  # 'otro' es el fallback, no un objetivo semántico
        legible = code.replace("_", " ")
        result = matcher.match(legible)
        assert result["code"] == code
        assert result["status"] == STATUS_MATCHED


def test_batch_match_devuelve_una_entrada_por_descripcion(matcher):
    descripciones = [c[0] for c in CASOS_MATCH]
    resultados = matcher.batch_match(descripciones)
    assert len(resultados) == len(descripciones)
    assert all(set(r) == {"code", "confidence", "status", "description"} for r in resultados)


def test_umbral_configurable(matcher):
    # Un mismo texto que con umbral default matchea, con un umbral por encima de su
    # confianza cae a revisión — el umbral es lo único que cambia el veredicto.
    texto = "reinicio de inversor"
    base = matcher.match(texto)
    assert base["status"] == STATUS_MATCHED
    estricto = FallaResolutionMatcher(RESOLUTION_CODES, threshold=base["confidence"] + 1)
    assert estricto.match(texto)["status"] == STATUS_PENDING


def test_constructor_rechaza_codigos_vacios():
    with pytest.raises(ValueError):
        FallaResolutionMatcher([])
