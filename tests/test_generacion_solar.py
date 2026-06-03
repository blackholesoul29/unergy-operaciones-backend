"""Tests de _normalize_name (matching fuzzy de nombres de proyecto Solenium)."""
from app.api.v1.generacion_solar import _normalize_name


def test_lowercase_and_spaces():
    assert _normalize_name("El Copey") == "el copey"


def test_strips_accents():
    assert _normalize_name("Piñón Valledupar") == "pinon valledupar"


def test_code_with_underscores_and_digits():
    assert _normalize_name("COLCEST55P2_VALLEDUPAR_NORTE") == "colcest55p2 valledupar norte"


def test_collapses_punctuation_and_whitespace():
    assert _normalize_name("  La  Jagua-de-Ibirico  ") == "la jagua de ibirico"


def test_empty_and_none_safe():
    assert _normalize_name("") == ""
    assert _normalize_name(None) == ""
