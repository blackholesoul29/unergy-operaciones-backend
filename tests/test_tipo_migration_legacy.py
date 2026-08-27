"""`tipo_migration` no puede volver a comerse el catálogo estructurado.

Regresión del bug encontrado el 2026-08-27: la regla era «legacy = código no
numérico», y los códigos de la taxonomía estructurada (`red.baja_tension`)
tampoco son numéricos. Resultado: `tipo_migration` re-apuntaba 5.086 fallas a un
tipo numérico de respaldo en **cada arranque**, y `fallas_tipo_backfill` --que
corre después-- las devolvía. 23 arranques en 16 horas.

Lo que hacía invisible la mitad de la pelea: `tipo_migration` escribe con
`.update(synchronize_session=False)`, un UPDATE masivo que no pasa por los hooks
de auditoría. `audit_log` registraba a la víctima y nunca al culpable.
"""
import pytest

from app.main import es_tipo_legacy
from app.services.fallas.estructura import ESTRUCTURA_FALLAS, codigos_estructurados


@pytest.fixture
def estructurados():
    return codigos_estructurados()


# ── Los tres tipos de código que conviven en fallas_cat_tipos ────────────────

@pytest.mark.parametrize("codigo", ["corte_energia", "falla_inversor", "otro"])
def test_los_snake_case_viejos_si_son_legacy(codigo, estructurados):
    """Para esto se escribió la migración: son los que hay que re-apuntar."""
    assert es_tipo_legacy(codigo, estructurados) is True


@pytest.mark.parametrize("codigo", ["1.1", "2.0", "2.1", "2.8", "4.6", "5.1"])
def test_los_numericos_no_son_legacy(codigo, estructurados):
    """Son el destino de la migración, no su origen."""
    assert es_tipo_legacy(codigo, estructurados) is False


def test_ningun_codigo_estructurado_es_legacy(estructurados):
    """El bug, en una línea: estos no son numéricos, pero tampoco son viejos."""
    assert estructurados, "la estructura no puede estar vacía"

    culpables = [c for c in estructurados if es_tipo_legacy(c, estructurados)]

    assert culpables == [], (
        f"{len(culpables)} códigos estructurados tratados como legacy: {culpables[:5]}")


def test_el_caso_exacto_que_produjo_el_bug(estructurados):
    """`red.baja_tension` es el patrón de los 5.086 que se reescribían."""
    assert es_tipo_legacy("red.baja_tension", estructurados) is False


# ── La derivación desde ESTRUCTURA_FALLAS ────────────────────────────────────

def test_los_codigos_salen_de_la_estructura_y_no_de_una_lista_aparte(estructurados):
    """Agregar una categoría no puede volver a reabrir esto."""
    for cat in ESTRUCTURA_FALLAS:
        for clave in ("opciones", "tipos_falla"):
            for item in cat.get(clave, []):
                esperado = f"{cat['codigo']}.{item['codigo']}"
                assert esperado in estructurados, f"falta {esperado}"


def test_una_categoria_nueva_queda_protegida_sola(estructurados, monkeypatch):
    """Simula agregar una categoría: sus códigos dejan de ser legacy sin tocar main."""
    from app.services.fallas import estructura

    nueva = {"codigo": "meteorologia", "etiqueta": "Meteorología", "tipo": "opcion",
             "opciones": [{"codigo": "granizo", "etiqueta": "Granizo"}]}
    monkeypatch.setattr(estructura, "ESTRUCTURA_FALLAS", ESTRUCTURA_FALLAS + [nueva])

    ampliados = estructura.codigos_estructurados()

    assert es_tipo_legacy("meteorologia.granizo", estructurados) is True   # antes
    assert es_tipo_legacy("meteorologia.granizo", ampliados) is False      # después


def test_codigo_vacio_o_nulo_no_es_legacy(estructurados):
    """Un tipo sin código no se re-apunta a ciegas."""
    assert es_tipo_legacy(None, estructurados) is False
    assert es_tipo_legacy("", estructurados) is False


# ── El orden de las tareas de arranque ───────────────────────────────────────

def test_el_backfill_corre_pegado_a_tipo_migration():
    """Red de seguridad: si vuelve a haber dos escritores de `fallas.tipo_id`,
    la ventana de datos inconsistentes servidos por la API dura una tarea."""
    import inspect

    from app.main import _deferred_init

    fuente = inspect.getsource(_deferred_init)
    i = fuente.index('("tipo_migration"')
    j = fuente.index('("fallas_tipo_backfill"')

    assert j > i, "fallas_tipo_backfill tiene que ir DESPUÉS de tipo_migration"
    entre = fuente[i:j].count('("')
    assert entre == 1, f"hay {entre - 1} tareas entre las dos; deben ir pegadas"
