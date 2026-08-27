"""La réplica de Exposición Energía en Bolsa, como aritmética pura.

Validada contra XM con error mediano de 0,0057% sobre 70 períodos. El signo y la
granularidad horaria no son detalles: invertir el signo produce ceros donde hay deuda,
y agregar a día antes de multiplicar da otro número.
"""
import datetime

import pytest

from app.services.garantias_modelo.replica import (
    exposicion_dia,
    exposicion_periodo,
    precio_implicito,
)

D1 = datetime.date(2026, 8, 1)
D2 = datetime.date(2026, 8, 2)


def test_exposicion_dia_es_compras_menos_ventas():
    # Convención de XM: positivo = comprador neto = se debe dinero = sube la garantía.
    r = exposicion_dia(compras=[10.0] * 24, ventas=[4.0] * 24, precio=[100.0] * 24)
    assert r == pytest.approx(6.0 * 100.0 * 24)


def test_exposicion_dia_vendedor_neto_da_negativo():
    r = exposicion_dia(compras=[1.0] * 24, ventas=[5.0] * 24, precio=[100.0] * 24)
    assert r < 0


def test_exposicion_es_horaria_no_diaria():
    """El producto va hora a hora. Agregar a día primero da otro número cuando la
    energía correlaciona con el precio, que es el caso solar."""
    compras = [0.0] * 12 + [10.0] * 12
    ventas = [0.0] * 24
    precio = [50.0] * 12 + [200.0] * 12          # caro justo cuando hay energía
    horaria = exposicion_dia(compras=compras, ventas=ventas, precio=precio)
    neto_dia = sum(compras) - sum(ventas)
    precio_medio = sum(precio) / 24
    diaria = neto_dia * precio_medio
    assert horaria == pytest.approx(10.0 * 200.0 * 12)
    assert horaria != pytest.approx(diaria)


def test_exposicion_periodo_suma_los_dias():
    dias = {
        D1: {"compras": [10.0] * 24, "ventas": [4.0] * 24, "precio": [100.0] * 24},
        D2: {"compras": [10.0] * 24, "ventas": [4.0] * 24, "precio": [100.0] * 24},
    }
    assert exposicion_periodo(dias) == pytest.approx(2 * 6.0 * 100.0 * 24)


def test_exposicion_periodo_vacio_es_cero():
    assert exposicion_periodo({}) == 0.0


def test_exposicion_dia_longitudes_distintas_falla_ruidosamente():
    with pytest.raises(ValueError):
        exposicion_dia(compras=[1.0] * 24, ventas=[1.0] * 23, precio=[1.0] * 24)


def test_precio_implicito_reconcilia():
    """El precio implícito debe coincidir con el Precio de Bolsa Ponderado de XM.
    Si no coincide de forma sistemática, la ventana o los datos están mal."""
    r = precio_implicito(energia=[10.0] * 12 + [30.0] * 12,
                         precio=[100.0] * 12 + [200.0] * 12)
    assert r == pytest.approx((10 * 100 * 12 + 30 * 200 * 12) / (10 * 12 + 30 * 12))


def test_precio_implicito_sin_energia_es_none():
    assert precio_implicito(energia=[0.0] * 24, precio=[100.0] * 24) is None
