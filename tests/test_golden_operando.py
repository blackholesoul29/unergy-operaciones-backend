"""Golden test de `GET /comercial/proyectos-operando` — precondición de la Fase 4.

La Fase 4 del refactor cambia de dónde lee `app/services/comercial.py` y la
respuesta **tiene que salir idéntica**. Este archivo tiene dos mitades:

1. **El comparador y los invariantes, probados con datos sintéticos.** Corren
   siempre. Prueban que la herramienta caza los cambios que tiene que cazar --
   un golden que no detecta nada pasa igual de verde que uno que funciona, y
   esa es la forma más fácil de creerse protegido sin estarlo.

2. **La captura real, si existe.** `tests/golden/proyectos_operando.json` no
   está versionado: lo genera `scripts/capturar_golden_operando.py` contra la
   API viva. Si no está, esos tests se saltan con instrucciones.
"""
import json
import os

import pytest

from golden_operando import comparar, plantas, revisar_invariantes

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "proyectos_operando.json")
ACTUAL = os.path.join(os.path.dirname(__file__), "golden", "proyectos_operando_actual.json")


def _planta(**detalles):
    return {"id": 1, "nombre": "MiniGranja 0001", "detalles": {
        "operador_red_id": 3, **detalles}}


def _arbol(*plantas_):
    return [{"ppa": {"id": 10}, "proyectos": list(plantas_)}]


# ── 1 · El comparador ────────────────────────────────────────────────────────

def test_dos_capturas_iguales_no_tienen_diferencias():
    a = _arbol(_planta(potencia_dc_kwp=300.0))
    assert comparar(a, json.loads(json.dumps(a))) == []


def test_caza_un_valor_cambiado_y_dice_donde():
    difs = comparar(_arbol(_planta(potencia_dc_kwp=300.0)),
                    _arbol(_planta(potencia_dc_kwp=301.0)))

    assert len(difs) == 1
    assert "potencia_dc_kwp" in difs[0] and "300.0" in difs[0] and "301.0" in difs[0]


def test_caza_un_campo_que_desaparece():
    """El riesgo real de la Fase 4: una columna que se mueve y deja de salir."""
    difs = comparar(_arbol(_planta(sub_project="ayura")), _arbol(_planta()))

    assert len(difs) == 1 and "sub_project" in difs[0] and "desapareció" in difs[0]


def test_caza_un_null_que_se_relleno():
    """`operador_red_id` null es señal. Rellenarlo es romper el contrato."""
    difs = comparar(_arbol({"id": 1, "detalles": {"operador_red_id": None}}),
                    _arbol({"id": 1, "detalles": {"operador_red_id": 7}}))

    assert len(difs) == 1 and "None" in difs[0] and "7" in difs[0]


def test_el_orden_de_la_lista_no_cuenta_como_diferencia():
    a = _arbol({"id": 1, "detalles": {}}, {"id": 2, "detalles": {}})
    b = _arbol({"id": 2, "detalles": {}}, {"id": 1, "detalles": {}})

    assert comparar(a, b) == []


def test_una_lista_que_pierde_elementos_si_cuenta():
    difs = comparar(_arbol({"id": 1, "detalles": {}}, {"id": 2, "detalles": {}}),
                    _arbol({"id": 1, "detalles": {}}))

    assert any("2 a 1 elementos" in d for d in difs)


def test_un_numero_que_pasa_a_texto_se_reporta_como_tipo():
    difs = comparar({"p50_anual_kwh": 1200.5}, {"p50_anual_kwh": "1200.5"})

    assert len(difs) == 1 and "cambió el tipo" in difs[0]


# ── 2 · Los tres invariantes de `05` §4 ──────────────────────────────────────

def test_arbol_sano_no_viola_ningun_invariante():
    sano = _arbol(_planta(
        energia_promedio_origen="medido",
        energia_promedio_detalle={"dias_con_datos": 30, "ventana_desde": "2026-07-01",
                                  "ventana_hasta": "2026-07-31", "actualizado_en": "2026-08-01"},
        simulacion={"p50_mensual_kwh": [1.0] * 12, "p50_anual_kwh": 12.0}))

    assert revisar_invariantes(sano) == []


def test_invariante_1_operador_red_id_no_puede_faltar():
    sin_operador = _arbol({"id": 1, "detalles": {"potencia_dc_kwp": 300.0}})

    fallas = revisar_invariantes(sin_operador)

    assert len(fallas) == 1 and "operador_red_id" in fallas[0]


def test_invariante_1_operador_red_id_en_null_es_valido():
    """Null es la señal de 'no está en el catálogo'. No es una violación."""
    assert revisar_invariantes(_arbol({"id": 1, "detalles": {"operador_red_id": None}})) == []


def test_invariante_2_p50_anual_con_serie_incompleta():
    """Sumar 7 meses y llamarlo anual es exactamente lo que no puede pasar."""
    fallas = revisar_invariantes(_arbol(_planta(
        simulacion={"p50_mensual_kwh": [1.0] * 7, "p50_anual_kwh": 7.0})))

    assert len(fallas) == 1 and "7 meses" in fallas[0]


def test_invariante_2_serie_de_7_meses_con_anual_null_esta_bien():
    assert revisar_invariantes(_arbol(_planta(
        simulacion={"p50_mensual_kwh": [1.0] * 7, "p50_anual_kwh": None}))) == []


@pytest.mark.parametrize("origen", ["estimado", "declarado"])
def test_invariante_3_detalle_lleno_con_origen_sin_medicion(origen):
    fallas = revisar_invariantes(_arbol(_planta(
        energia_promedio_origen=origen,
        energia_promedio_detalle={"dias_con_datos": 30, "ventana_desde": None,
                                  "ventana_hasta": None, "actualizado_en": None})))

    assert len(fallas) == 1 and "dias_con_datos" in fallas[0]


@pytest.mark.parametrize("origen", ["estimado", "declarado"])
def test_invariante_3_el_detalle_tiene_que_estar_aunque_venga_vacio(origen):
    fallas = revisar_invariantes(_arbol(_planta(energia_promedio_origen=origen)))

    assert len(fallas) == 1 and "desapareció" in fallas[0]


# ── 3 · Contra la captura real ───────────────────────────────────────────────

_SIN_GOLDEN = f"""No hay captura en {GOLDEN}.
Generala con:  python scripts/capturar_golden_operando.py <URL_BASE> <TOKEN>
Es precondicion de la Fase 4 y conviene capturarla YA: cada dia que pasa el
arbol cambia y la diferencia se vuelve mas dificil de atribuir."""


@pytest.mark.skipif(not os.path.exists(GOLDEN), reason=_SIN_GOLDEN)
def test_la_captura_guardada_cumple_los_invariantes():
    with open(GOLDEN, encoding="utf-8") as fh:
        base = json.load(fh)

    fallas = revisar_invariantes(base["respuesta"])

    assert fallas == [], "la captura base ya viola invariantes:\n" + "\n".join(fallas)


@pytest.mark.skipif(not (os.path.exists(GOLDEN) and os.path.exists(ACTUAL)),
                    reason="hacen falta la captura base y una captura nueva")
def test_la_respuesta_de_hoy_es_identica_a_la_capturada():
    with open(GOLDEN, encoding="utf-8") as fh:
        base = json.load(fh)
    with open(ACTUAL, encoding="utf-8") as fh:
        actual = json.load(fh)

    difs = comparar(base["respuesta"], actual["respuesta"])

    assert difs == [], (
        f"la salida cambió respecto de {base.get('capturado_en')} "
        f"({len(difs)} diferencias):\n" + "\n".join(difs[:40]))


@pytest.mark.skipif(not os.path.exists(GOLDEN), reason=_SIN_GOLDEN)
def test_la_captura_no_esta_vacia():
    """Un golden de 0 plantas pasa todos los tests y no protege nada."""
    with open(GOLDEN, encoding="utf-8") as fh:
        base = json.load(fh)

    assert len(plantas(base["respuesta"])) > 0, "la captura no tiene ni una planta"
