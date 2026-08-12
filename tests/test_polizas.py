# unergy-operaciones-backend/tests/test_polizas.py
"""Pólizas: cálculo de derivados (presupuesto/IPP) y upsert conectado a un
proyecto real, con sesión sqlite en memoria (mismo patrón que
test_arr_arrendadores_crud.py: se llaman las funciones del router
directamente, sin pasar por FastAPI)."""
from app.api.v1.polizas import calcular_derivados


def test_calcular_derivados_suma_presupuesto():
    total, lucro = calcular_derivados(
        mano_obra=1_000_000, estructura=2_000_000, paneles=3_000_000,
        inversores=1_500_000, otros=500_000,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total == 8_000_000
    assert lucro is None


def test_calcular_derivados_presupuesto_vacio_da_none():
    total, _ = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total is None


def test_calcular_derivados_presupuesto_parcial_suma_lo_disponible():
    total, _ = calcular_derivados(
        mano_obra=1_000_000, estructura=None, paneles=None, inversores=None, otros=0,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total == 1_000_000


def test_calcular_derivados_lucro_cesante():
    # % indexación = 110/100 = 1.1 -> tarifa indexada = 200*1.1=220 -> lucro = 220*1000
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=100, ipp_provisional=110, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro == 220_000


def test_calcular_derivados_ipp_base_cero_no_divide():
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=0, ipp_provisional=110, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro is None


def test_calcular_derivados_ipp_incompleto_no_calcula():
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=100, ipp_provisional=None, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro is None
