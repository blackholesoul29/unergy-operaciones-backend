"""Los diffs fantasma de `audit_log`: `{"antes": 0.038, "despues": 0.038}`.

Regresion del hallazgo de `docs/refactor/01-decisiones.md` D-24 §e. La columna
es `NUMERIC`, asi que el valor cargado es `Decimal`; el que llega del JSON del
`PATCH` es `float`. `Decimal('0.0380') != 0.038` es True en Python, asi que
`_diff_attrs` registraba un cambio que no habia cambiado nada -- y los dos lados
salian identicos en el log, porque `_serialize` castea el Decimal a float.

Los cuatro casos son los que aparecen de verdad en produccion (ver
`esquema-bd-produccion/historico_tarifas.txt`).

`set_committed_value` simula el valor "como si viniera de la base", que es lo
que hace falta para que el atributo tenga historia sin tocar la BD.
"""
from decimal import Decimal

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.models.contratos import ContratoServicio
from app.services.audit import _diff_attrs


def _contrato(campo, cargado, asignado):
    """Un contrato con `campo` cargado de la BD y despues reasignado."""
    c = ContratoServicio()
    set_committed_value(c, campo, cargado)
    setattr(c, campo, asignado)
    return c


def test_decimal_y_float_del_mismo_numero_no_son_un_cambio():
    """El fantasma: el front reenvia 0.038 sin tocarlo y la BD tiene 0.0380."""
    contrato = _contrato("tarifa_admin", Decimal("0.0380"), 0.038)

    assert _diff_attrs(contrato) is None


def test_cero_a_valor_si_es_un_cambio():
    """Contrato 108: cgm y representacion pasaron de 0.0 a 5.0."""
    contrato = _contrato("tarifa_cgm", Decimal("0.000000"), 5.0)

    assert _diff_attrs(contrato) == {
        "tarifa_cgm": {"antes": 0.0, "despues": 5.0}
    }


def test_null_a_valor_si_es_un_cambio():
    """Contratos 1, 2 y 205: primer llenado de un campo vacio."""
    contrato = _contrato("tarifa_representacion", None, 3.0)

    assert _diff_attrs(contrato) == {
        "tarifa_representacion": {"antes": None, "despues": 3.0}
    }


def test_una_renegociacion_de_verdad_si_queda_registrada():
    """Lo que el arreglo NO debe silenciar: 3,8 % -> 5 % (el caso Cedillanos)."""
    contrato = _contrato("tarifa_admin", Decimal("0.0380"), 0.05)

    assert _diff_attrs(contrato) == {
        "tarifa_admin": {"antes": 0.038, "despues": 0.05}
    }


@pytest.mark.parametrize("cargado,asignado", [
    (Decimal("5.000000"), 5.0),      # exacto en binario: nunca fue fantasma
    (Decimal("6.000000"), 6.0),
    (Decimal("0.000000"), 0.0),
    (Decimal("0.0500"), 0.05),
    (Decimal("0.0380"), 0.038),      # el unico que si lo era
])
def test_ningun_reenvio_del_mismo_valor_queda_registrado(cargado, asignado):
    """Barre las tarifas que existen en los datos, exactas y no exactas."""
    assert _diff_attrs(_contrato("tarifa_cgm", cargado, asignado)) is None
