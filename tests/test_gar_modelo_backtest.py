"""Backtest: error por componente, no solo del total."""
import pytest

from app.services.garantias_modelo.backtest import (
    error_relativo,
    resumen_error,
)


def test_error_relativo_normal():
    assert error_relativo(predicho=110.0, real=100.0) == pytest.approx(10.0)


def test_error_relativo_usa_valor_absoluto_del_real():
    """El real puede ser negativo; el error no debe cambiar de signo por eso."""
    assert error_relativo(predicho=-110.0, real=-100.0) == pytest.approx(10.0)


def test_error_relativo_real_cero_es_none():
    """Dividir por un real de cero da infinito y contamina la mediana. La exposición
    neta es un residuo pequeño de números grandes: cerca de cero, el porcentaje engaña."""
    assert error_relativo(predicho=5.0, real=0.0) is None


def test_resumen_error_reporta_mediana_y_percentiles():
    r = resumen_error([1.0, 2.0, 3.0, 4.0, 100.0])
    assert r["n"] == 5
    assert r["mediana"] == pytest.approx(3.0)
    assert r["max"] == pytest.approx(100.0)


def test_resumen_error_ignora_none():
    r = resumen_error([1.0, None, 3.0])
    assert r["n"] == 2


def test_resumen_error_vacio():
    r = resumen_error([])
    assert r["n"] == 0
    assert r["mediana"] is None


def test_resumen_error_cuenta_dentro_de_umbrales():
    r = resumen_error([0.001, 0.5, 3.0, 20.0])
    assert r["dentro_0_01"] == 1
    assert r["dentro_1"] == 2
    assert r["dentro_5"] == 3
