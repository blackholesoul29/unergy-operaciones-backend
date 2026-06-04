"""Tests de proyecto_matching — matcher fuzzy nombre externo → tabla proyectos.

Previamente SIN tests pese a usarse en fallas, generación y ahora el seed CGM
(_run_cgm_seed). El seed depende de que `find_proyecto_by_name` devuelva None ante
entrada vacía/whitespace para NO enlazar un contrato a un proyecto arbitrario
(el bug del viejo `LIKE %%`). Estos tests fijan esa propiedad.
"""
import types
from app.utils.proyecto_matching import find_proyecto_by_name, _normalize


def _proy(pid, comercial, bitacora=None, clientes=None, alias=None):
    return types.SimpleNamespace(
        id=pid, nombre_comercial=comercial, nombre_bitacora=bitacora,
        nombre_clientes=clientes, alias_monitoreo=alias)


class _FakeDB:
    """Stub mínimo: db.query(Proyecto).all() → lista fija (sin DB real, estilo conftest)."""
    def __init__(self, proyectos):
        self._p = proyectos

    def query(self, _model):
        proyectos = self._p

        class _Q:
            def all(self):
                return proyectos
        return _Q()


def test_normalize_strips_accents_case_and_punct():
    assert _normalize("Solá-rÍa 2!") == "sola ria 2"
    assert _normalize("  CURUMANÍ  ") == "curumani"


def test_empty_or_whitespace_or_none_returns_none():
    # La propiedad de la que depende el seed CGM: nunca enlaza ante entrada vacía.
    db = _FakeDB([_proy(1, "Curumaní Solar")])
    assert find_proyecto_by_name(db, "") is None
    assert find_proyecto_by_name(db, "   ") is None
    assert find_proyecto_by_name(db, None) is None


def test_exact_match_is_accent_insensitive():
    db = _FakeDB([_proy(1, "Planta X"), _proy(2, "Curumaní Solar")])
    assert find_proyecto_by_name(db, "curumani solar").id == 2


def test_partial_match_when_input_contained_in_name():
    db = _FakeDB([_proy(1, "Planta Solar"), _proy(2, "Granja Solar La Esperanza")])
    assert find_proyecto_by_name(db, "Esperanza").id == 2


def test_alias_monitoreo_match():
    db = _FakeDB([_proy(1, "Proyecto Uno", alias="GSE|La Esperanza")])
    assert find_proyecto_by_name(db, "La Esperanza").id == 1


def test_unrelated_name_returns_none_not_arbitrary():
    # Antes, un LIKE ingenuo podía devolver el primer proyecto; el matcher devuelve None.
    db = _FakeDB([_proy(1, "Curumaní Solar"), _proy(2, "Planta Norte")])
    assert find_proyecto_by_name(db, "Zzzz Inexistente Qwxyz") is None


def test_fuzzy_false_does_not_mislink_numbered_sibling():
    # CRÍTICO para el seed CGM: familias numeradas (Polaris 1/2, Taurus IX/X) tienen
    # ratio fuzzy ~0.93. Con fuzzy=False NO debe mal-enlazar 'Polaris 2' a 'Polaris 1':
    # sin match seguro → None (reconciliable), no un proyecto_id equivocado.
    db = _FakeDB([_proy(1, "GD Polaris 1")])
    assert find_proyecto_by_name(db, "GD Polaris 2", fuzzy=False) is None


def test_fuzzy_true_default_would_match_sibling():
    # Documenta POR QUÉ el seed usa fuzzy=False: con el default, el paso SequenceMatcher
    # (≥0.75) SÍ enlaza el hermano — comportamiento correcto para búsquedas, peligroso para seed.
    db = _FakeDB([_proy(1, "GD Polaris 1")])
    assert find_proyecto_by_name(db, "GD Polaris 2").id == 1
