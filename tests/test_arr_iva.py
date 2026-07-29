"""IVA calculado (19%) sobre el canon a facturar, solo si el contrato es
responsable_iva=True."""
from app.services.arr_calculator import calcular_iva


def test_iva_cuando_responsable():
    assert calcular_iva(4_691_747, True) == 891_432  # round(4_691_747 * 0.19)


def test_sin_iva_cuando_no_responsable():
    assert calcular_iva(4_691_747, False) is None


def test_sin_iva_si_no_hay_canon():
    assert calcular_iva(None, True) is None
